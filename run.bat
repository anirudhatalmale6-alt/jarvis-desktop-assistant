@echo off
title Jarvis
cd /d "%~dp0"
if not exist ".venv" (
  echo   Jarvis has not been set up yet. Run setup.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python -m jarvis.main
if errorlevel 1 pause
