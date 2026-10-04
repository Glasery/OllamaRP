@echo off
chcp 65001 > nul
cd /d "%~dp0"

rem Same as run_app.bat but with a visible console: if the app fails
rem to start, the error text stays on screen.

set "PY=python"
if exist "venv\Scripts\python.exe" set "PY=venv\Scripts\python.exe"

"%PY%" main.py
echo.
echo --- app exited ---
pause
