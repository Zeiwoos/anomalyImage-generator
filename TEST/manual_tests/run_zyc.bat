@echo off
setlocal
cd /d "%~dp0"
if defined PYTHON_EXE (
  "%PYTHON_EXE%" -B run_zyc.py %*
) else (
  python -B run_zyc.py %*
)
exit /b %errorlevel%
