@echo off
set "PYTHON_EXE="

if defined PIPELINE_PYTHON if exist "%PIPELINE_PYTHON%" (
  set "PYTHON_EXE=%PIPELINE_PYTHON%"
  exit /b 0
)

if exist "%~dp0python_path.local.txt" goto read_local_python

:search_standard_locations
if defined CONDA_PREFIX if exist "%CONDA_PREFIX%\python.exe" (
  set "PYTHON_EXE=%CONDA_PREFIX%\python.exe"
  exit /b 0
)

if exist "%~dp0.venv\Scripts\python.exe" (
  set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
  exit /b 0
)

where python >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_EXE=python"
  exit /b 0
)

echo ERROR: Python was not found.
exit /b 1

:read_local_python
set /p PYTHON_EXE=<"%~dp0python_path.local.txt"
if exist "%PYTHON_EXE%" exit /b 0
set "PYTHON_EXE="
goto search_standard_locations
