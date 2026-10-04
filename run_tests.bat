@echo off
chcp 65001 > nul
cd /d "%~dp0"

rem Run the logic tests (no GUI, no network). Window stays open.

set "PY=python"
if exist "venv\Scripts\python.exe" set "PY=venv\Scripts\python.exe"

"%PY%" test_logic.py
echo.
pause
