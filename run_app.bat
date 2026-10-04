@echo off
cd /d "%~dp0"

rem Launch the GUI with no console window (pythonw).

if exist "venv\Scripts\pythonw.exe" goto venv
start "" pythonw main.py
exit /b 0

:venv
start "" "venv\Scripts\pythonw.exe" main.py
exit /b 0
