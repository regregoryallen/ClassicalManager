@echo off
setlocal

REM Classical Manager - ReplayGain tagger, from a source checkout.
REM
REM The Windows counterpart of ./rgtag.py on Linux: runs the tagger in the
REM project's virtual environment so it need not be activated first.
REM run.bat is the same thing for the application itself.
REM
REM All arguments are passed through:
REM   rgtag.bat --help
REM   rgtag.bat --library "My Collection"
REM
REM Dry-run is the default. Nothing is written without --write.

if not exist "%~dp0venv\Scripts\python.exe" (
    echo.
    echo  ERROR: Virtual environment not found.
    echo  Run setup.bat first to install dependencies.
    echo.
    pause
    exit /b 1
)

REM Always a console program: it is interactive, prompts before writing,
REM and reports progress as it goes. Never pythonw.
"%~dp0venv\Scripts\python.exe" "%~dp0rgtag.py" %*
