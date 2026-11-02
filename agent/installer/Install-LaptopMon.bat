@echo off
setlocal
title Laptop Productivity Monitoring - Setup Wizard

echo ==========================================================
echo   Laptop Productivity Monitoring - Setup Wizard
echo ==========================================================
echo Starting installation setup...

:: Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    python3 --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo [ERROR] Python was not detected on this machine.
        echo Please ensure Python 3.10+ is installed or install via:
        echo   winget install Python.Python.3.12
        pause
        exit /b 1
    ) else (
        set PY_CMD=python3
    )
) else (
    set PY_CMD=python
)

:: Run GUI setup wizard passing any passed token or arguments
%PY_CMD% "%~dp0gui_installer.py" %*

if %errorlevel% neq 0 (
    echo.
    echo Setup exited or was cancelled.
    pause
)
