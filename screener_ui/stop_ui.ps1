$ErrorActionPreference = "Stop"

$uiDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $uiDir ".runtime\ui.pid"
$stopped = $false

if (Test-Path -LiteralPath $pidFile) {
    $pidText = (Get-Content -Path $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($pidText -match "^\d+$") {
        taskkill /PID $pidText /T /F | Out-Null
        $stopped = $true
        Write-Output "UI stopped (PID $pidText)."
    }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}

$listeners = netstat -ano | Select-String ":5173\s+.*LISTENING"
foreach ($line in $listeners) {
    $pidText = ($line.ToString().Trim() -split "\s+")[-1]
    if ($pidText -match "^\d+$") {
        taskkill /PID $pidText /T /F | Out-Null
        $stopped = $true
        Write-Output "UI stopped from port 5173 (PID $pidText)."
    }
}

if (-not $stopped) {
    Write-Output "UI is not running."
}
