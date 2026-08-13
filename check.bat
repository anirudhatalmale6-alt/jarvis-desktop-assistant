@echo off
title Jarvis - system check
cd /d "%~dp0"
.venv\Scripts\python check.py
echo.
pause
