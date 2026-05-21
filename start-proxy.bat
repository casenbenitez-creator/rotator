@echo off
cd /d "%~dp0"
python start.py --proxy-only
if %errorlevel% neq 0 pause
