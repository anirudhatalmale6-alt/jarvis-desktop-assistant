@echo off
title Jarvis - first time setup
cd /d "%~dp0"
echo.
echo   Setting up Jarvis. This takes a few minutes the first time.
echo.

where py >nul 2>nul
if errorlevel 1 (
  echo   Python is not installed.
  echo.
  echo   Get it from https://www.python.org/downloads/
  echo   IMPORTANT: tick "Add Python to PATH" on the first screen of the installer.
  echo.
  pause
  exit /b 1
)

if not exist ".venv" (
  echo   Creating a private Python environment...
  py -3 -m venv .venv || goto :failed
)

echo   Downloading the parts Jarvis needs...
.venv\Scripts\python -m pip install --upgrade pip --quiet
.venv\Scripts\python -m pip install -r requirements.txt || goto :failed

if not exist "settings.txt" (
  copy settings-example.txt settings.txt >nul
  echo.
  echo   Created settings.txt. Opening it now - paste your API key into it,
  echo   save the file, then close Notepad to carry on.
  echo.
  notepad settings.txt
)

echo.
echo   Setup finished. Checking everything works...
echo.
.venv\Scripts\python check.py
echo.
pause
exit /b 0

:failed
echo.
echo   Setup did not finish. The error is above.
echo   Send me that message and I will sort it.
pause
exit /b 1
