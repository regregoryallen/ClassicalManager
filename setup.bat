@echo off
setlocal

echo.
echo  Classical Music Playlist Manager - Setup
echo  ==========================================
echo.

REM --- Check Python is installed ---
python --version >NUL 2>&1
if errorlevel 1 (
    echo  ERROR: Python is not installed or not on PATH.
    echo.
    echo  Install Python 3.12+ from https://www.python.org/downloads/
    echo    - Check "Add python.exe to PATH"
    echo    - Leave "tcl/tk and IDLE" checked ^(required for the GUI^)
    echo.
    echo  Or install via winget:
    echo    winget install Python.Python.3.12
    echo.
    goto :fail
)

REM --- Check Python version >= 3.12 ---
python -c "import sys; exit(0 if sys.version_info >= (3, 12) else 1)"
if errorlevel 1 (
    echo  ERROR: Python 3.12 or newer is required.
    for /f "tokens=*" %%v in ('python --version') do echo  Found: %%v
    echo.
    echo  Install Python 3.12+ from https://www.python.org/downloads/
    echo.
    goto :fail
)

for /f "tokens=*" %%v in ('python --version') do echo  Found %%v

REM --- Create venv if needed ---
if not exist "venv\Scripts\python.exe" (
    echo  Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo  ERROR: Failed to create virtual environment.
        goto :fail
    )
) else (
    echo  Virtual environment already exists.
)

REM --- Install dependencies ---
echo  Installing dependencies...
call venv\Scripts\activate.bat
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo  ERROR: Failed to install dependencies.
    goto :fail
)

REM --- Copy config if needed ---
if not exist "config.json" (
    copy config.example.json config.json >NUL
    echo  Created config.json from template.
) else (
    echo  config.json already exists, skipping.
)

echo.
echo  Setup complete!
echo.

REM --- Offer desktop shortcut ---
set /p "SHORTCUT=  Create a desktop shortcut? (Y/N): "
if /i "%SHORTCUT%"=="Y" (
    powershell -Command ^
        "$ws = New-Object -ComObject WScript.Shell; ^
         $s = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\ClassicalManager.lnk'); ^
         $s.TargetPath = '%~dp0run.bat'; ^
         $s.WorkingDirectory = '%~dp0'; ^
         $s.IconLocation = '%~dp0app_icon.ico,0'; ^
         $s.WindowStyle = 7; ^
         $s.Save()"
    if errorlevel 1 (
        echo  WARNING: Could not create shortcut.
    ) else (
        echo  Desktop shortcut created.
    )
)

echo.
echo  Run the app with:
echo    run.bat           ^(GUI^)
echo    run.bat --cli -h  ^(CLI help^)
echo.
goto :end

:fail
echo.
echo  Setup failed. See errors above.
echo.
pause
exit /b 1

:end
pause
