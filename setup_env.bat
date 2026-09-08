@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PROJECT_DIR=%~dp0"
set "VENV_DIR=%PROJECT_DIR%.venv"

where python >nul 2>nul
if errorlevel 1 goto missing_python

if not exist "%VENV_DIR%\Scripts\python.exe" (
  python -m venv "%VENV_DIR%"
  if errorlevel 1 goto setup_failed
)

"%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto setup_failed
"%VENV_DIR%\Scripts\python.exe" -m pip install -r "%PROJECT_DIR%requirements.txt"
if errorlevel 1 goto setup_failed

>"%PROJECT_DIR%python_path.local.txt" echo %VENV_DIR%\Scripts\python.exe
echo.
echo Environment ready: %VENV_DIR%
echo Next: edit config.json, then run start_review_tool.bat --check.
exit /b 0

:missing_python
echo ERROR: A system Python is required to create .venv.
echo Install Python 3.10 or newer, or activate an existing Conda environment.
pause
exit /b 1

:setup_failed
echo ERROR: Environment setup failed. Review the messages above.
pause
exit /b 1
