$ErrorActionPreference = "Stop"

$rootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $rootDir "venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = "python"
}

$runtimeDir = Join-Path $rootDir ".runtime"
$logDir = Join-Path $rootDir "logs"
New-Item -ItemType Directory -Force -Path $runtimeDir, $logDir | Out-Null

$existing = netstat -ano | Select-String ":8787\s+.*LISTENING"
if ($existing) {
    $pidText = ($existing[0].ToString().Trim() -split "\s+")[-1]
    Set-Content -Path (Join-Path $runtimeDir "backend.pid") -Value $pidText
    Write-Output "Backend already running at http://127.0.0.1:8787 (PID $pidText)."
    exit 0
}

$outLog = Join-Path $logDir "backend.out.log"
$errLog = Join-Path $logDir "backend.err.log"
$process = Start-Process `
    -FilePath $python `
    -ArgumentList @("-m", "uvicorn", "screener_ui.backend.app:app", "--host", "127.0.0.1", "--port", "8787") `
    -WorkingDirectory $rootDir `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog `
    -WindowStyle Hidden `
    -PassThru

Start-Sleep -Seconds 3
$listening = netstat -ano | Select-String ":8787\s+.*LISTENING"
if ($listening) {
    $pidText = ($listening[0].ToString().Trim() -split "\s+")[-1]
    Set-Content -Path (Join-Path $runtimeDir "backend.pid") -Value $pidText
    Write-Output "Backend started at http://127.0.0.1:8787 (PID $pidText)."
} else {
    Set-Content -Path (Join-Path $runtimeDir "backend.pid") -Value $process.Id
    Write-Output "Backend process started (PID $($process.Id)), but port 8787 is not listening yet."
    Write-Output "Check logs: $errLog"
}
