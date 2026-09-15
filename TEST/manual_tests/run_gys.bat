@echo off
setlocal
cd /d "%~dp0"
if defined PYTHON_EXE (
  "%PYTHON_EXE%" -B run_gys.py %*
) else (
  python -B run_gys.py %*
)
exit /b %errorlevel%
