@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PROJECT_DIR=%~dp0"
set "CONFIG_FILE=%PROJECT_DIR%config.json"

if not exist "%CONFIG_FILE%" goto missing_config
call "%PROJECT_DIR%find_python.bat"
if errorlevel 1 goto missing_python

pushd "%PROJECT_DIR%"
if /I "%~1"=="--check" goto check_environment
"%PYTHON_EXE%" -B -m anomaly_factory.cli --config "%CONFIG_FILE%" review
set "EXIT_CODE=%ERRORLEVEL%"
popd
if not "%EXIT_CODE%"=="0" goto launch_failed
exit /b 0

:check_environment
"%PYTHON_EXE%" -B -c "import sys, PIL; print('Python ' + sys.version.split()[0]); print('Pillow ' + PIL.__version__)"
"%PYTHON_EXE%" -B -m anomaly_factory.cli --config "%CONFIG_FILE%" doctor
set "EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %EXIT_CODE%

:missing_python
echo ERROR: No usable Python was found.
echo Run setup_env.bat, activate a Conda environment, or set PIPELINE_PYTHON.
pause
exit /b 1

:missing_config
echo ERROR: config.json was not found:
echo %CONFIG_FILE%
pause
exit /b 1

:launch_failed
echo.
echo ERROR: The review server failed to start.
echo Run start_review_tool.bat --check and configure dataset.root in config.json.
pause
exit /b 1
