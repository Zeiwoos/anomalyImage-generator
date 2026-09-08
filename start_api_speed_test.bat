@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PROJECT_DIR=%~dp0"
call "%PROJECT_DIR%find_python.bat"
if errorlevel 1 (
  echo Run setup_env.bat, activate a Conda environment, or set PIPELINE_PYTHON.
  pause
  exit /b 1
)
pushd "%PROJECT_DIR%"
"%PYTHON_EXE%" -B -m anomaly_factory.speed_test_server --config "%PROJECT_DIR%config.json" --port 8897
set "EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %EXIT_CODE%
