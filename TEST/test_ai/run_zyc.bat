@echo off
setlocal
cd /d "%~dp0"
call "..\..\find_python.bat"
if errorlevel 1 exit /b 1
"%PYTHON_EXE%" -B run_zyc.py %*
exit /b %errorlevel%
