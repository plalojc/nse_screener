@echo off
setlocal EnableExtensions

set "ROOT_DIR=%~dp0"
cd /d "%ROOT_DIR%"

set "ACTION=%~1"
if "%ACTION%"=="" set "ACTION=start"
set "PORT=%SCREENER_PORT%"
if "%PORT%"=="" set "PORT=8787"
set "HOST=%SCREENER_HOST%"
if "%HOST%"=="" set "HOST=0.0.0.0"
set "RUNTIME_DIR=%ROOT_DIR%.runtime"
set "PID_FILE=%RUNTIME_DIR%\screener.pid"
set "LOG_FILE=%RUNTIME_DIR%\screener.log"

if /I "%ACTION%"=="start" goto start
if /I "%ACTION%"=="stop" goto stop
if /I "%ACTION%"=="restart" goto restart
if /I "%ACTION%"=="status" goto status

echo Usage: run_screener.bat [start^|stop^|restart^|status]
exit /b 1

:ensure_runtime
if not exist "%RUNTIME_DIR%" mkdir "%RUNTIME_DIR%"
exit /b 0

:is_running
if not exist "%PID_FILE%" exit /b 1
set /p OLD_PID=<"%PID_FILE%"
if "%OLD_PID%"=="" exit /b 1
tasklist /FI "PID eq %OLD_PID%" 2>NUL | findstr /R /C:"[ ]%OLD_PID%[ ]" >NUL
exit /b %ERRORLEVEL%

:kill_matching
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*uvicorn*' -and $_.CommandLine -like '*screener_ui.backend.app:app*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
exit /b 0

:build_ui
if not exist "screener_ui\frontend\package.json" (
  echo [ERROR] React frontend package.json not found.
  exit /b 1
)
pushd "screener_ui\frontend"
if not exist "node_modules" (
  echo [UI] Installing frontend dependencies...
  call npm install
  if errorlevel 1 exit /b 1
)
echo [UI] Building React frontend...
call npm run build
if errorlevel 1 exit /b 1
popd
exit /b 0

:python_cmd
set "PYTHON_CMD=python"
if exist "%ROOT_DIR%venv\Scripts\python.exe" set "PYTHON_CMD=%ROOT_DIR%venv\Scripts\python.exe"
exit /b 0

:start
call :ensure_runtime
call :is_running
if "%ERRORLEVEL%"=="0" (
  echo [Screener] Already running on PID %OLD_PID%.
  echo URL: http://127.0.0.1:%PORT%
  exit /b 0
)
set "PORT_PID="
for /f %%P in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "(Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess"') do set "PORT_PID=%%P"
if not "%PORT_PID%"=="" (
  echo [ERROR] Port %PORT% is already in use by PID %PORT_PID%. Stop that process or use SCREENER_PORT.
  exit /b 1
)
call :build_ui
if errorlevel 1 exit /b 1
call :python_cmd
set "SCREENER_AGENT_ROOT=%ROOT_DIR:~0,-1%"
echo [Screener] Starting backend + UI on %HOST%:%PORT%...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Start-Process -FilePath '%PYTHON_CMD%' -ArgumentList @('-m','uvicorn','screener_ui.backend.app:app','--host','%HOST%','--port','%PORT%') -WorkingDirectory '%ROOT_DIR%' -RedirectStandardOutput '%LOG_FILE%' -RedirectStandardError '%LOG_FILE%.err' -PassThru -WindowStyle Hidden; Set-Content -Path '%PID_FILE%' -Value $p.Id"
if errorlevel 1 exit /b 1
set /p NEW_PID=<"%PID_FILE%"
echo [Screener] Started on PID %NEW_PID%.
echo URL: http://127.0.0.1:%PORT%
exit /b 0

:stop
call :is_running
if not "%ERRORLEVEL%"=="0" (
  echo [Screener] No PID file process found. Cleaning any matching screener server process...
  call :kill_matching
  if exist "%PID_FILE%" del "%PID_FILE%"
  exit /b 0
)
echo [Screener] Stopping PID %OLD_PID%...
taskkill /PID %OLD_PID% /T /F >NUL
call :kill_matching
if exist "%PID_FILE%" del "%PID_FILE%"
echo [Screener] Stopped.
exit /b 0

:restart
call "%~f0" stop
call "%~f0" start
exit /b %ERRORLEVEL%

:status
call :is_running
if "%ERRORLEVEL%"=="0" (
  echo [Screener] Running on PID %OLD_PID%.
  echo URL: http://127.0.0.1:%PORT%
) else (
  echo [Screener] Not running.
)
exit /b 0
