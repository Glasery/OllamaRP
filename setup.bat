@echo off
chcp 65001 > nul
cd /d "%~dp0"

rem One-time setup: create venv and install dependencies.
rem Requires Python installed (python.org, "Add to PATH" checked).

if exist "venv\Scripts\python.exe" goto deps
echo Creating virtual environment venv...
python -m venv venv
if errorlevel 1 goto err

:deps
echo Upgrading pip...
"venv\Scripts\python.exe" -m pip install --upgrade pip
echo Installing dependencies from requirements.txt...
"venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto err

echo.
echo Done.
echo   run_app.bat    - start the app
echo   run_tests.bat  - run the tests
echo.
pause
exit /b 0

:err
echo.
echo Error. Make sure Python is installed and on PATH (run: python --version).
echo.
pause
exit /b 1
