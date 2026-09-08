@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PROJECT_DIR=%~dp0"
call "%PROJECT_DIR%find_python.bat"
if errorlevel 1 exit /b 1
pushd "%PROJECT_DIR%"
"%PYTHON_EXE%" -B -m anomaly_factory.cli --config "%PROJECT_DIR%config.json" %*
set "EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %EXIT_CODE%
