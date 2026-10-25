@echo off
chcp 65001 > nul
title TextImageGradioApp4

cd /d "%~dp0"

"venv\Scripts\python.exe" "TextImageGradioApp4.py"

pause