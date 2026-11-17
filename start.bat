@echo off
setlocal
cd /d "%~dp0"
title INDRA BOT SYSTEM - Local Starter

echo.
echo  INDRA BOT SYSTEM - local starter
echo  =================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo  Looking for Python 3.10 or newer...
    py -3 -c "import sys; sys.exit(not sys.version_info.__ge__((3, 10)))" >nul 2>&1
    if not errorlevel 1 (
        py -3 -m venv .venv
    ) else (
        python -c "import sys; sys.exit(not sys.version_info.__ge__((3, 10)))" >nul 2>&1
        if errorlevel 1 (
            echo  Python 3.10 or newer was not found.
            echo  Install it from https://www.python.org/downloads/
            echo  During installation, select "Add Python to PATH".
            echo  Then double-click start.bat again.
            echo.
            pause
            exit /b 1
        )
        python -m venv .venv
    )
    if not exist ".venv\Scripts\python.exe" (
        echo  Could not create the Python environment. See the error above.
        pause
        exit /b 1
    )
)

echo  Checking dependencies. The first run needs an internet connection...
".venv\Scripts\python.exe" -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 (
    echo.
    echo  Could not install dependencies. Check your internet connection and try again.
    pause
    exit /b 1
)

if not exist ".env" (
    copy ".env.example" ".env" >nul
    if errorlevel 1 (
        echo  Could not create .env. Make sure you extracted the entire project.
        pause
        exit /b 1
    )
    echo  Created .env. You can add your Discord bot from the dashboard.
)

echo.
echo  Starting at http://127.0.0.1:5000
echo  Keep this window open. Press Ctrl+C or close it to stop the app.
echo.
".venv\Scripts\python.exe" local_start.py
if errorlevel 1 (
    echo.
    echo  The app could not start. See the error above.
    pause
    exit /b 1
)
echo.
echo  The app has stopped.
pause
