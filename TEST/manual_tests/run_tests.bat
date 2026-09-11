@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
for %%I in ("%~dp0..\..") do set "PROJECT_DIR=%%~fI"
for %%I in ("%~dp0.") do set "TEST_DIR=%%~fI"

call "%PROJECT_DIR%\find_python.bat"
if errorlevel 1 goto missing_python

set "TEST_PATTERN=%~1"
if not defined TEST_PATTERN set "TEST_PATTERN=test_*.py"

pushd "%PROJECT_DIR%"
"%PYTHON_EXE%" -B "%TEST_DIR%\runner.py" --pattern "%TEST_PATTERN%"
set "EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %EXIT_CODE%

:missing_python
echo ERROR: No usable Python was found.
echo Run setup_env.bat, activate Conda, or set PIPELINE_PYTHON.
exit /b 1

