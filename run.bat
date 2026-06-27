@echo off
setlocal

REM --- Check venv exists ---
if not exist "venv\Scripts\python.exe" (
    echo.
    echo  ERROR: Virtual environment not found.
    echo  Run setup.bat first to install dependencies.
    echo.
    pause
    exit /b 1
)

REM --- Check dependencies installed ---
venv\Scripts\python.exe -c "import customtkinter" >NUL 2>&1
if errorlevel 1 (
    echo.
    echo  ERROR: Dependencies not installed.
    echo  Run setup.bat first to install dependencies.
    echo.
    pause
    exit /b 1
)

REM --- Launch the app ---
REM Use pythonw (no console window) for GUI mode, python for CLI mode
echo %* | findstr /i "\-\-cli" >NUL 2>&1
if errorlevel 1 (
    start "" /b venv\Scripts\pythonw.exe main.py %*
) else (
    call venv\Scripts\activate.bat
    python main.py %*
)
