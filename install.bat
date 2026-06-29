@echo off
setlocal enabledelayedexpansion
REM =====================================================================
REM Classical Manager - Windows Installer
REM =====================================================================
REM
REM Installs Classical Manager to a local directory, sets up a Python
REM virtual environment, configures the application, and creates desktop
REM and Start Menu shortcuts.
REM
REM Usage:
REM   install.bat              Interactive install / update
REM   install.bat --uninstall  Remove a previous installation
REM
REM =====================================================================

set "SCRIPT_DIR=%~dp0"
REM Remove trailing backslash
if "!SCRIPT_DIR:~-1!"=="\" set "SCRIPT_DIR=!SCRIPT_DIR:~0,-1!"

set "APP_NAME=classical-manager"
set "APP_DISPLAY_NAME=Classical Manager"
set "DEFAULT_INSTALL_DIR=%LOCALAPPDATA%\ClassicalManager"

REM Resolved during setup
set "INSTALL_DIR="
set "PYTHON_CMD="

if "%~1"=="--uninstall" goto :do_uninstall

REM =====================================================================
REM Banner
REM =====================================================================

echo.
echo  +----------------------------------------------+
echo  ^|    Classical Manager - Windows Installer      ^|
echo  +----------------------------------------------+
echo.

REM =====================================================================
REM Prerequisites
REM =====================================================================

echo  --- Prerequisites ---
echo.
echo  Checking for Python 3.12+...

REM Try py launcher first (installed with python.org installer)
py -3 -c "import sys; exit(0 if sys.version_info >= (3, 12) else 1)" >NUL 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=py -3"
    goto :python_found
)

REM Try python directly
python -c "import sys; exit(0 if sys.version_info >= (3, 12) else 1)" >NUL 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=python"
    goto :python_found
)

echo.
echo  ERROR: Python 3.12+ is required but was not found.
echo.
echo  Install from https://www.python.org/downloads/
echo    - Check "Add python.exe to PATH"
echo    - Leave "tcl/tk and IDLE" checked (required for the GUI^)
echo.
echo  Or:  winget install Python.Python.3.12
echo.
goto :fail

:python_found
for /f "tokens=*" %%v in ('!PYTHON_CMD! --version') do echo   Found %%v

echo  Checking for Tkinter...
!PYTHON_CMD! -c "import tkinter" >NUL 2>&1
if errorlevel 1 (
    echo.
    echo  WARNING: Tkinter is not available.
    echo  The GUI will not work, but the CLI will.
    echo  Reinstall Python with "tcl/tk and IDLE" checked.
    echo.
) else (
    echo   Tkinter is available.
)
echo.

REM =====================================================================
REM Install location
REM =====================================================================

echo  --- Installation ---
echo.
echo  Install location:
echo    1^) Default:  %DEFAULT_INSTALL_DIR%
echo    2^) Custom path
echo.
set "INSTALL_CHOICE=1"
set /p "INSTALL_CHOICE=  Choose (1 or 2) [1]: "

if "!INSTALL_CHOICE!"=="2" (
    set /p "INSTALL_DIR=  Enter install path: "
) else (
    set "INSTALL_DIR=!DEFAULT_INSTALL_DIR!"
)

if "!INSTALL_DIR!"=="" set "INSTALL_DIR=!DEFAULT_INSTALL_DIR!"

REM Guard against installing to source directory
if /i "!INSTALL_DIR!"=="!SCRIPT_DIR!" (
    echo.
    echo  ERROR: Cannot install to the source directory.
    echo  Choose a different location.
    echo.
    goto :fail
)

echo.
echo  Install directory: !INSTALL_DIR!
echo.

REM =====================================================================
REM Source validation
REM =====================================================================

echo  Validating source files...
set "MISSING=0"
if not exist "!SCRIPT_DIR!\main.py" (
    echo   Missing: main.py
    set "MISSING=1"
)
if not exist "!SCRIPT_DIR!\requirements.txt" (
    echo   Missing: requirements.txt
    set "MISSING=1"
)
if not exist "!SCRIPT_DIR!\music_manager\" (
    echo   Missing: music_manager\
    set "MISSING=1"
)
if "!MISSING!"=="1" (
    echo.
    echo  ERROR: This script must be run from the ClassicalManager source directory.
    goto :fail
)
echo   Source files validated.

REM Offer git pull
if exist "!SCRIPT_DIR!\.git\" (
    echo.
    set "GIT_PULL=Y"
    set /p "GIT_PULL=  Git repository detected. Pull latest changes? (Y/N) [Y]: "
    if /i "!GIT_PULL!"=="Y" (
        echo  Running git pull...
        pushd "!SCRIPT_DIR!"
        git pull
        popd
        echo   Repository updated.
    )
)
echo.

REM =====================================================================
REM File deployment
REM =====================================================================

echo  Deploying files to !INSTALL_DIR!...

if not exist "!INSTALL_DIR!\" mkdir "!INSTALL_DIR!"

robocopy "!SCRIPT_DIR!" "!INSTALL_DIR!" /MIR /NFL /NDL /NJH /NJS /NP ^
    /XF config.json gui_prefs.json *.db *.db-wal *.db-shm *.pyc ^
        install.sh classical-manager-cron.sh .gitignore cron.log ^
        music_manager.save-db ^
    /XD venv TestData .git __pycache__ music_manager.save-db >NUL 2>&1

if errorlevel 8 (
    echo  ERROR: File deployment failed.
    goto :fail
)
echo   Application files deployed.
echo.

REM =====================================================================
REM Virtual environment
REM =====================================================================

echo  --- Virtual Environment ---
echo.

set "VENV_PYTHON=!INSTALL_DIR!\venv\Scripts\python.exe"

REM Check if existing venv has the right Python version
if exist "!VENV_PYTHON!" (
    set "EXISTING_VER="
    "!VENV_PYTHON!" -c "import sys; print(str(sys.version_info.major)+'.'+str(sys.version_info.minor))" > "%TEMP%\cm_pyver.txt" 2>NUL
    set /p EXISTING_VER=<"%TEMP%\cm_pyver.txt"
    del "%TEMP%\cm_pyver.txt" 2>NUL
    set "TARGET_VER="
    !PYTHON_CMD! -c "import sys; print(str(sys.version_info.major)+'.'+str(sys.version_info.minor))" > "%TEMP%\cm_pyver.txt" 2>NUL
    set /p TARGET_VER=<"%TEMP%\cm_pyver.txt"
    del "%TEMP%\cm_pyver.txt" 2>NUL

    if "!EXISTING_VER!"=="!TARGET_VER!" (
        echo  Virtual environment exists ^(Python !EXISTING_VER!^) - updating dependencies...
    ) else (
        echo  Python version changed ^(!EXISTING_VER! -^> !TARGET_VER!^) - recreating...
        rmdir /s /q "!INSTALL_DIR!\venv" 2>NUL
        echo  Creating virtual environment...
        !PYTHON_CMD! -m venv "!INSTALL_DIR!\venv"
        if errorlevel 1 (
            echo  ERROR: Failed to create virtual environment.
            goto :fail
        )
    )
) else (
    echo  Creating virtual environment...
    !PYTHON_CMD! -m venv "!INSTALL_DIR!\venv"
    if errorlevel 1 (
        echo  ERROR: Failed to create virtual environment.
        goto :fail
    )
)

echo  Installing dependencies (this may take a moment^)...
"!VENV_PYTHON!" -m pip install --upgrade pip --quiet >NUL 2>&1
"!VENV_PYTHON!" -m pip install -r "!INSTALL_DIR!\requirements.txt" --quiet
if errorlevel 1 (
    echo.
    echo  ERROR: Failed to install dependencies.
    goto :fail
)

REM Verify key imports
"!VENV_PYTHON!" -c "import customtkinter; import mutagen; import peewee; import typer" >NUL 2>&1
if errorlevel 1 (
    echo  WARNING: Some dependencies could not be verified.
) else (
    echo   Dependencies installed and verified.
)
echo.

REM =====================================================================
REM Configuration interview
REM =====================================================================

echo  --- Configuration ---
echo.

set "CONFIG_FILE=!INSTALL_DIR!\config.json"

REM Handle existing config
if exist "!CONFIG_FILE!" (
    echo  An existing config.json was found.
    echo    1^) Keep current configuration
    echo    2^) Reconfigure from scratch
    echo    3^) Show current config (tokens redacted^)
    echo.
    set "CFG_CHOICE=1"
    set /p "CFG_CHOICE=  Choose [1]: "

    if "!CFG_CHOICE!"=="3" (
        echo.
        "!VENV_PYTHON!" -c "import json; cfg=json.load(open(r'!CONFIG_FILE!')); p=cfg.get('targets',{}).get('plex',{}); t=p.get('token',''); p.update({'token':'****'} if t else {}); print(json.dumps(cfg,indent=2))" 2>NUL
        echo.
        set "KEEP_CFG=Y"
        set /p "KEEP_CFG=  Keep this configuration? (Y/N) [Y]: "
        if /i "!KEEP_CFG!"=="Y" (
            echo   Keeping existing configuration.
            goto :after_config
        )
        if /i "!KEEP_CFG!"=="y" (
            echo   Keeping existing configuration.
            goto :after_config
        )
    ) else if "!CFG_CHOICE!"=="2" (
        REM Fall through to interview
        echo.
    ) else (
        echo   Keeping existing configuration.
        goto :after_config
    )
)

echo  Let's configure Classical Manager.
echo  Press Enter to accept defaults shown in [brackets].
echo.

REM --- Database path ---
echo  Database
echo    The database stores your scanned library, works, and playlist profiles.
echo    Leave empty to use the default location inside the install directory.
set "CFG_DB_PATH="
set /p "CFG_DB_PATH=  Database file path: "
echo.

REM --- Plex target ---
set "CFG_PLEX_ENABLED=0"
set "CFG_PLEX_URL="
set "CFG_PLEX_TOKEN="
set "CFG_PLEX_TOKEN_ENV="
set "CFG_PLEX_SECTION="
set "PLEX_RULE_COUNT=0"

echo  Plex Integration
echo    Push playlists directly to your Plex media server.
set "PLEX_YN=N"
set /p "PLEX_YN=  Configure Plex? (Y/N) [N]: "
if /i "!PLEX_YN!"=="Y" (
    set "CFG_PLEX_ENABLED=1"
    echo.

    set "CFG_PLEX_URL=http://localhost:32400"
    set /p "CFG_PLEX_URL=  Plex server URL [http://localhost:32400]: "

    echo.
    echo    How should the Plex authentication token be provided?
    echo      1^) Enter the token now (stored in config.json^)
    echo      2^) Use an environment variable (more secure^)
    set "TOKEN_CHOICE=2"
    set /p "TOKEN_CHOICE=  Choose [2]: "

    if "!TOKEN_CHOICE!"=="1" (
        echo.
        echo    Note: Token will be visible as you type.
        echo    Use option 2 (environment variable^) for better security.
        set /p "CFG_PLEX_TOKEN=  Plex token: "
        if "!CFG_PLEX_TOKEN!"=="" (
            echo    WARNING: Token is empty. You can add it later in config.json.
        )
    ) else (
        set "CFG_PLEX_TOKEN_ENV=PLEX_TOKEN"
        set /p "CFG_PLEX_TOKEN_ENV=  Environment variable name [PLEX_TOKEN]: "
        echo    Remember to set this variable in your system environment.
    )

    echo.
    set "CFG_PLEX_SECTION=Music"
    set /p "CFG_PLEX_SECTION=  Plex music library section name [Music]: "

    echo.
    echo    Path rewrite rules translate local file paths to paths the Plex
    echo    server sees.  For example:
    echo      find:    C:\Users\me\Music
    echo      replace: /data/music
    echo.
    set "ADD_PLEX_RULES=N"
    set /p "ADD_PLEX_RULES=  Add Plex path rewrite rules? (Y/N) [N]: "
    if /i "!ADD_PLEX_RULES!"=="Y" call :collect_plex_rules
)
echo.

REM --- M3U target ---
set "CFG_M3U_ENABLED=0"
set "CFG_M3U_STYLE="
set "CFG_M3U_BASE="
set "M3U_RULE_COUNT=0"

echo  M3U Export
echo    Generate .m3u playlist files for use in other music players.
set "M3U_YN=Y"
set /p "M3U_YN=  Configure M3U export? (Y/N) [Y]: "
if /i "!M3U_YN!"=="Y" (
    set "CFG_M3U_ENABLED=1"
    echo.

    echo    Path style determines how file paths appear in the .m3u files:
    echo      1^) absolute              Full paths
    echo      2^) relative_to_playlist  Relative to the .m3u file location
    set "STYLE_CHOICE=1"
    set /p "STYLE_CHOICE=  Path style [1]: "
    if "!STYLE_CHOICE!"=="2" (
        set "CFG_M3U_STYLE=relative_to_playlist"
    ) else (
        set "CFG_M3U_STYLE=absolute"
    )

    echo.
    echo    Base path is an optional prefix prepended to absolute paths in M3U files.
    echo    Leave empty unless your player expects a specific root path.
    set "CFG_M3U_BASE="
    set /p "CFG_M3U_BASE=  Base path: "

    echo.
    set "ADD_M3U_RULES=N"
    set /p "ADD_M3U_RULES=  Add M3U path rewrite rules? (Y/N) [N]: "
    if /i "!ADD_M3U_RULES!"=="Y" call :collect_m3u_rules
)

REM --- Write config.json ---
echo.
echo  Writing config.json...

set "CFG_OUTPUT_PATH=!CONFIG_FILE!"
call :write_config_py
"!VENV_PYTHON!" "!CFG_PY!" 2>NUL
if errorlevel 1 (
    echo  ERROR: Failed to write config.json.
    del "!CFG_PY!" 2>NUL
    goto :fail
)
del "!CFG_PY!" 2>NUL
echo   Configuration written to !CONFIG_FILE!

:after_config
echo.

REM =====================================================================
REM CLI wrapper
REM =====================================================================

echo  --- Integration ---
echo.
echo  Creating CLI wrapper...

> "!INSTALL_DIR!\!APP_NAME!.bat" echo @echo off
>> "!INSTALL_DIR!\!APP_NAME!.bat" echo REM Classical Manager CLI wrapper - auto-generated by install.bat
>> "!INSTALL_DIR!\!APP_NAME!.bat" echo echo %%* ^| findstr /i "\-\-cli" ^>NUL 2^>^&1
>> "!INSTALL_DIR!\!APP_NAME!.bat" echo if errorlevel 1 (
>> "!INSTALL_DIR!\!APP_NAME!.bat" echo     start "" /b "%%~dp0venv\Scripts\pythonw.exe" "%%~dp0main.py" %%*
>> "!INSTALL_DIR!\!APP_NAME!.bat" echo ) else (
>> "!INSTALL_DIR!\!APP_NAME!.bat" echo     "%%~dp0venv\Scripts\python.exe" "%%~dp0main.py" %%*
>> "!INSTALL_DIR!\!APP_NAME!.bat" echo )

echo   CLI wrapper created: !INSTALL_DIR!\!APP_NAME!.bat

REM Check if install dir is on PATH
echo ;%PATH%; | findstr /i /c:";!INSTALL_DIR!;" >NUL 2>&1
if errorlevel 1 (
    echo.
    echo  !INSTALL_DIR! is not on your PATH.
    set "ADD_PATH=Y"
    set /p "ADD_PATH=  Add it to your user PATH? (Y/N) [Y]: "
    if /i "!ADD_PATH!"=="Y" (
        powershell -NoProfile -Command "[Environment]::SetEnvironmentVariable('Path', [Environment]::GetEnvironmentVariable('Path', 'User') + ';!INSTALL_DIR!', 'User')"
        if not errorlevel 1 (
            echo   Added to user PATH. Open a new terminal for it to take effect.
        ) else (
            echo   WARNING: Could not modify PATH. Add it manually:
            echo     !INSTALL_DIR!
        )
    ) else (
        echo   To use the CLI from any directory, add this to your PATH:
        echo     !INSTALL_DIR!
    )
)
echo.

REM =====================================================================
REM Shortcuts
REM =====================================================================

echo  Creating desktop shortcut...
powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\Classical Manager.lnk'); $s.TargetPath = '!INSTALL_DIR!\venv\Scripts\pythonw.exe'; $s.Arguments = '\"!INSTALL_DIR!\main.py\"'; $s.WorkingDirectory = '!INSTALL_DIR!'; $s.IconLocation = '!INSTALL_DIR!\app_icon.ico,0'; $s.WindowStyle = 7; $s.Save()" >NUL 2>&1
if errorlevel 1 (
    echo   WARNING: Could not create desktop shortcut.
) else (
    echo   Desktop shortcut created.
)

echo  Creating Start Menu shortcut...
set "START_MENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs"
powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('!START_MENU!\Classical Manager.lnk'); $s.TargetPath = '!INSTALL_DIR!\venv\Scripts\pythonw.exe'; $s.Arguments = '\"!INSTALL_DIR!\main.py\"'; $s.WorkingDirectory = '!INSTALL_DIR!'; $s.IconLocation = '!INSTALL_DIR!\app_icon.ico,0'; $s.WindowStyle = 7; $s.Save()" >NUL 2>&1
if errorlevel 1 (
    echo   WARNING: Could not create Start Menu shortcut.
) else (
    echo   Start Menu shortcut created.
)
echo.

REM =====================================================================
REM Summary
REM =====================================================================

echo  +----------------------------------------------+
echo  ^|         Installation Complete!                ^|
echo  +----------------------------------------------+
echo.
echo   Install location:   !INSTALL_DIR!
echo   Config file:        !INSTALL_DIR!\config.json
if "!CFG_DB_PATH!"=="" (
    echo   Database:           !INSTALL_DIR!\music_manager.db
) else (
    echo   Database:           !CFG_DB_PATH!
)
echo   CLI command:         !APP_NAME!
echo   Desktop shortcut:    Desktop\Classical Manager
echo   Start Menu shortcut: Start Menu\Classical Manager
echo.
echo  Getting started:
echo    Launch the GUI:    Double-click the desktop or Start Menu shortcut
echo    CLI help:          !APP_NAME! --cli --help
echo    Scan a library:    !APP_NAME! --cli scan --library "My Collection"
echo    Edit config:       notepad "!INSTALL_DIR!\config.json"
echo.
echo  Uninstall:
echo    !SCRIPT_DIR!\install.bat --uninstall
echo.

goto :end


REM =====================================================================
REM Uninstall
REM =====================================================================

:do_uninstall
echo.
echo  +----------------------------------------------+
echo  ^|    Classical Manager - Uninstall              ^|
echo  +----------------------------------------------+
echo.

REM Find installation
set "INSTALL_DIR="
if exist "!DEFAULT_INSTALL_DIR!\main.py" (
    set "INSTALL_DIR=!DEFAULT_INSTALL_DIR!"
) else (
    echo  No installation found at !DEFAULT_INSTALL_DIR!
    echo.
    set /p "INSTALL_DIR=  Enter the install path (or press Enter to cancel): "
    if "!INSTALL_DIR!"=="" (
        echo  Uninstall cancelled.
        goto :end
    )
    if not exist "!INSTALL_DIR!\main.py" (
        echo  ERROR: No installation found at !INSTALL_DIR!
        goto :fail
    )
)

echo  Installation found at: !INSTALL_DIR!
echo.

REM Offer to backup user data
set "BACKUP_DIR=%USERPROFILE%\classical-manager-backup"
set "PRESERVED=0"
if exist "!INSTALL_DIR!\config.json" (
    set "BACKUP_YN=Y"
    set /p "BACKUP_YN=  Preserve database and config? Copies to !BACKUP_DIR! (Y/N) [Y]: "
    if /i "!BACKUP_YN!"=="Y" (
        if not exist "!BACKUP_DIR!\" mkdir "!BACKUP_DIR!"
        if exist "!INSTALL_DIR!\config.json" copy /y "!INSTALL_DIR!\config.json" "!BACKUP_DIR!\" >NUL
        if exist "!INSTALL_DIR!\gui_prefs.json" copy /y "!INSTALL_DIR!\gui_prefs.json" "!BACKUP_DIR!\" >NUL
        for %%f in ("!INSTALL_DIR!\*.db") do copy /y "%%f" "!BACKUP_DIR!\" >NUL
        echo   User data backed up to !BACKUP_DIR!\
        set "PRESERVED=1"
    )
)

echo.
set "CONFIRM=Y"
set /p "CONFIRM=  Remove !INSTALL_DIR! and all shortcuts? (Y/N) [Y]: "
if /i not "!CONFIRM!"=="Y" (
    echo  Uninstall cancelled.
    goto :end
)

REM Remove install directory
echo  Removing installation...
rmdir /s /q "!INSTALL_DIR!" 2>NUL
echo   Install directory removed.

REM Remove shortcuts
del "%USERPROFILE%\Desktop\Classical Manager.lnk" 2>NUL
del "%USERPROFILE%\Desktop\ClassicalManager.lnk" 2>NUL
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Classical Manager.lnk" 2>NUL
echo   Shortcuts removed.

REM Remove from PATH
powershell -NoProfile -Command "$p = [Environment]::GetEnvironmentVariable('Path', 'User'); if ($p -and $p.Contains('!INSTALL_DIR!')) { $parts = $p.Split(';') | Where-Object { $_ -ne '!INSTALL_DIR!' }; [Environment]::SetEnvironmentVariable('Path', ($parts -join ';'), 'User'); Write-Host '  Removed from user PATH.' }" 2>NUL

echo.
echo  Classical Manager has been uninstalled.
if "!PRESERVED!"=="1" (
    echo  Your data was saved to !BACKUP_DIR!\
)
echo.
goto :end


REM =====================================================================
REM Subroutine: Collect Plex path rules
REM =====================================================================

:collect_plex_rules
set "PLEX_RULE_COUNT=0"

:plex_rule_loop
echo.
echo    Rule #!PLEX_RULE_COUNT!:
set "PR_FIND="
set /p "PR_FIND=    find (path prefix to match, empty to stop): "
if "!PR_FIND!"=="" goto :plex_rules_done
set "PR_REPLACE="
set /p "PR_REPLACE=    replace (replacement prefix): "
set "CFG_PLEX_RULE_!PLEX_RULE_COUNT!_FIND=!PR_FIND!"
set "CFG_PLEX_RULE_!PLEX_RULE_COUNT!_REPLACE=!PR_REPLACE!"
set /a PLEX_RULE_COUNT+=1
echo    Rule added: !PR_FIND! -^> !PR_REPLACE!
goto :plex_rule_loop

:plex_rules_done
exit /b


REM =====================================================================
REM Subroutine: Collect M3U path rules
REM =====================================================================

:collect_m3u_rules
set "M3U_RULE_COUNT=0"

:m3u_rule_loop
echo.
echo    Rule #!M3U_RULE_COUNT!:
set "MR_FIND="
set /p "MR_FIND=    find (path prefix to match, empty to stop): "
if "!MR_FIND!"=="" goto :m3u_rules_done
set "MR_REPLACE="
set /p "MR_REPLACE=    replace (replacement prefix): "
set "CFG_M3U_RULE_!M3U_RULE_COUNT!_FIND=!MR_FIND!"
set "CFG_M3U_RULE_!M3U_RULE_COUNT!_REPLACE=!MR_REPLACE!"
set /a M3U_RULE_COUNT+=1
echo    Rule added: !MR_FIND! -^> !MR_REPLACE!
goto :m3u_rule_loop

:m3u_rules_done
exit /b


REM =====================================================================
REM Subroutine: Write Python config generator to temp file
REM =====================================================================

:write_config_py
set "CFG_PY=%TEMP%\cm_config_gen.py"
> "!CFG_PY!" echo import json, os
>> "!CFG_PY!" echo.
>> "!CFG_PY!" echo config = {
>> "!CFG_PY!" echo     'active_library': 1,
>> "!CFG_PY!" echo     'db_path': os.environ.get('CFG_DB_PATH', ''),
>> "!CFG_PY!" echo     'autosave_interval': 60,
>> "!CFG_PY!" echo     'targets': {}
>> "!CFG_PY!" echo }
>> "!CFG_PY!" echo.
>> "!CFG_PY!" echo if os.environ.get('CFG_PLEX_ENABLED') == '1':
>> "!CFG_PY!" echo     plex = {
>> "!CFG_PY!" echo         'base_url': os.environ.get('CFG_PLEX_URL', ''),
>> "!CFG_PY!" echo         'music_section': os.environ.get('CFG_PLEX_SECTION', 'Music'),
>> "!CFG_PY!" echo         'path_rules': []
>> "!CFG_PY!" echo     }
>> "!CFG_PY!" echo     i = 0
>> "!CFG_PY!" echo     while True:
>> "!CFG_PY!" echo         f = os.environ.get(f'CFG_PLEX_RULE_{i}_FIND')
>> "!CFG_PY!" echo         if f is None:
>> "!CFG_PY!" echo             break
>> "!CFG_PY!" echo         r = os.environ.get(f'CFG_PLEX_RULE_{i}_REPLACE', '')
>> "!CFG_PY!" echo         plex['path_rules'].append({'find': f, 'replace': r})
>> "!CFG_PY!" echo         i += 1
>> "!CFG_PY!" echo     token = os.environ.get('CFG_PLEX_TOKEN', '')
>> "!CFG_PY!" echo     token_env = os.environ.get('CFG_PLEX_TOKEN_ENV', '')
>> "!CFG_PY!" echo     if token:
>> "!CFG_PY!" echo         plex['token'] = token
>> "!CFG_PY!" echo     if token_env:
>> "!CFG_PY!" echo         plex['token_env'] = token_env
>> "!CFG_PY!" echo     if not token and not token_env:
>> "!CFG_PY!" echo         plex['token_env'] = 'PLEX_TOKEN'
>> "!CFG_PY!" echo     config['targets']['plex'] = plex
>> "!CFG_PY!" echo.
>> "!CFG_PY!" echo if os.environ.get('CFG_M3U_ENABLED') == '1':
>> "!CFG_PY!" echo     m3u = {
>> "!CFG_PY!" echo         'path_style': os.environ.get('CFG_M3U_STYLE', 'absolute'),
>> "!CFG_PY!" echo         'base_path': os.environ.get('CFG_M3U_BASE', ''),
>> "!CFG_PY!" echo         'path_rules': []
>> "!CFG_PY!" echo     }
>> "!CFG_PY!" echo     i = 0
>> "!CFG_PY!" echo     while True:
>> "!CFG_PY!" echo         f = os.environ.get(f'CFG_M3U_RULE_{i}_FIND')
>> "!CFG_PY!" echo         if f is None:
>> "!CFG_PY!" echo             break
>> "!CFG_PY!" echo         r = os.environ.get(f'CFG_M3U_RULE_{i}_REPLACE', '')
>> "!CFG_PY!" echo         m3u['path_rules'].append({'find': f, 'replace': r})
>> "!CFG_PY!" echo         i += 1
>> "!CFG_PY!" echo     config['targets']['m3u'] = m3u
>> "!CFG_PY!" echo.
>> "!CFG_PY!" echo config_path = os.environ['CFG_OUTPUT_PATH']
>> "!CFG_PY!" echo with open(config_path, 'w') as fp:
>> "!CFG_PY!" echo     json.dump(config, fp, indent=2, ensure_ascii=False)
>> "!CFG_PY!" echo     fp.write('\n')
exit /b


REM =====================================================================
REM Exit points
REM =====================================================================

:fail
echo.
echo  Installation failed. See errors above.
echo.
pause
exit /b 1

:end
pause
