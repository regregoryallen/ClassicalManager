@echo off
REM =====================================================================
REM Classical Manager - Bootstrap Installer (Windows)
REM =====================================================================
REM
REM Double-click this file to install or update Classical Manager. It
REM downloads the current source from GitHub, runs the real installer,
REM and removes what it downloaded.
REM
REM This exists so there is something to double-click. The work is in the
REM .ps1 beside it; a .ps1 on its own cannot be run by double-clicking,
REM and a first-time user meets the execution-policy wall instead of an
REM installer. -ExecutionPolicy Bypass applies to this one process only
REM and changes no machine setting.
REM
REM From a terminal you can pass a tag:
REM   install-classical-manager.bat -Ref v3.11
REM =====================================================================

setlocal

set "PS1=%~dp0install-classical-manager.ps1"

if not exist "%PS1%" (
    echo.
    echo  ERROR: install-classical-manager.ps1 was not found next to this file.
    echo  Download both files into the same folder and run this one again.
    echo.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" %*
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
    echo  Installation did not complete ^(exit code %RC%^).
)
pause
exit /b %RC%
