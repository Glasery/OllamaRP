@echo off
REM Сборка автономного портабл-эксешника dist\OllamaRP.exe
REM Требуется активированное venv с установленным pyinstaller (см. requirements.txt).
cd /d "%~dp0"
venv\Scripts\python.exe -m PyInstaller --noconfirm OllamaRP.spec
echo.
echo Готово: dist\OllamaRP.exe
pause
