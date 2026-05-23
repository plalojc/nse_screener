@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "ROOT_DIR=%%~fI"
set "PYTHON_EXE=%ROOT_DIR%\venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"
set "CONTROL_SCRIPT=%SCRIPT_DIR%scripts\service_control.py"
for %%I in ("%PYTHON_EXE%") do set "PYTHON_EXE=%%~fI"
for %%I in ("%CONTROL_SCRIPT%") do set "CONTROL_SCRIPT=%%~fI"

"%PYTHON_EXE%" "%CONTROL_SCRIPT%" start-backend
exit /b %ERRORLEVEL%
