@echo off
REM ============================================================
REM  SELLER BOT - one-click starter for Windows
REM
REM  Double-click this file. On first run it will:
REM    1. create a private Python environment (folder .venv)
REM    2. install the small list of requirements
REM    3. create your .env settings file and open it in Notepad
REM  On every run it will:
REM    4. start the app and open http://localhost:5000 in your browser
REM ============================================================
title INDRA BOT SYSTEM
cd /d "%~dp0"

REM ---- Find Python. We try "python" first, then the "py" launcher ----
set PYTHON=
python --version >nul 2>nul
if not errorlevel 1 set PYTHON=python
if "%PYTHON%"=="" (
    py --version >nul 2>nul
    if not errorlevel 1 set PYTHON=py
)
if "%PYTHON%"=="" (
    echo.
    echo  Python was not found on this PC.
    echo.
    echo  Please install Python 3.10 or newer from:
    echo      https://www.python.org/downloads/
    echo.
    echo  IMPORTANT: on the very first installer screen,
    echo  tick the box "Add python.exe to PATH".
    echo  Then run this file again.
    echo.
    pause
    exit /b 1
)

REM ---- First run: create the private Python environment ----
if not exist ".venv\Scripts\python.exe" (
    echo  First run: creating a private Python environment...
    %PYTHON% -m venv .venv
    if errorlevel 1 (
        echo  Could not create the environment. Please read the message above.
        pause
        exit /b 1
    )
)

REM ---- Install / update the requirements (needs internet) ----
echo  Checking requirements (quick after the first time)...
".venv\Scripts\python.exe" -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 (
    echo.
    echo  Could not install the requirements. Check your internet
    echo  connection and run this file again.
    echo.
    pause
    exit /b 1
)

REM ---- First run: create the .env settings file from the example ----
if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo.
    echo  A settings file (.env) has been created for you.
    echo.
    echo  NEXT STEPS:
    echo    1. The file opens in Notepad in a moment.
    echo    2. Paste your Discord bot token after DISCORD_TOKEN=
    echo    3. Save the file (CTRL+S) and close it.
    echo    4. Run this file again.
    echo.
    echo  Where is my token? Discord Developer Portal -^> your app -^> Bot -^> Reset Token
    echo.
    start notepad ".env"
    pause
    exit /b 0
)

REM ---- Which port? (reads PORT=... from .env if you changed it) ----
set PORT=5000
for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    if /i "%%A"=="PORT" set PORT=%%B
)

REM ---- Start the app ----
echo.
echo  Starting INDRA BOT SYSTEM...
echo  The app will open in your browser at http://localhost:%PORT%
echo  Keep this window open. To stop the app, press CTRL+C here.
echo.
start "" "http://localhost:%PORT%"
".venv\Scripts\python.exe" "app.py"

echo.
echo  INDRA BOT SYSTEM has stopped.
pause
