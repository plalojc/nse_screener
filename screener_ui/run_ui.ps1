$ErrorActionPreference = "Stop"

$uiDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$frontendDir = Join-Path $uiDir "frontend"
$runtimeDir = Join-Path $uiDir ".runtime"
$logDir = Join-Path $uiDir "logs"
New-Item -ItemType Directory -Force -Path $runtimeDir, $logDir | Out-Null

$existing = netstat -ano | Select-String ":5173\s+.*LISTENING"
if ($existing) {
    $pidText = ($existing[0].ToString().Trim() -split "\s+")[-1]
    Set-Content -Path (Join-Path $runtimeDir "ui.pid") -Value $pidText
    Write-Output "UI already running at http://127.0.0.1:5173 (PID $pidText)."
    exit 0
}

if (-not (Test-Path -LiteralPath (Join-Path $frontendDir "node_modules"))) {
    Push-Location $frontendDir
    try {
        npm install
    } finally {
        Pop-Location
    }
}

$outLog = Join-Path $logDir "ui.out.log"
$errLog = Join-Path $logDir "ui.err.log"
$process = Start-Process `
    -FilePath "npm.cmd" `
    -ArgumentList @("run", "dev", "--", "--host", "127.0.0.1", "--port", "5173") `
    -WorkingDirectory $frontendDir `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog `
    -WindowStyle Hidden `
    -PassThru

Start-Sleep -Seconds 3
$listening = netstat -ano | Select-String ":5173\s+.*LISTENING"
if ($listening) {
    $pidText = ($listening[0].ToString().Trim() -split "\s+")[-1]
    Set-Content -Path (Join-Path $runtimeDir "ui.pid") -Value $pidText
    Write-Output "UI started at http://127.0.0.1:5173 (PID $pidText)."
} else {
    Set-Content -Path (Join-Path $runtimeDir "ui.pid") -Value $process.Id
    Write-Output "UI process started (PID $($process.Id)), but port 5173 is not listening yet."
    Write-Output "Check logs: $errLog"
}
