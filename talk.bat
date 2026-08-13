@echo off
title Jarvis - typing mode
cd /d "%~dp0"
.venv\Scripts\python -m jarvis.main --text
if errorlevel 1 pause
