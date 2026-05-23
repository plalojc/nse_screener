$ErrorActionPreference = "Stop"

$rootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $rootDir ".runtime\backend.pid"
$stopped = $false

if (Test-Path -LiteralPath $pidFile) {
    $pidText = (Get-Content -Path $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($pidText -match "^\d+$") {
        taskkill /PID $pidText /T /F | Out-Null
        $stopped = $true
        Write-Output "Backend stopped (PID $pidText)."
    }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}

$listeners = netstat -ano | Select-String ":8787\s+.*LISTENING"
foreach ($line in $listeners) {
    $pidText = ($line.ToString().Trim() -split "\s+")[-1]
    if ($pidText -match "^\d+$") {
        taskkill /PID $pidText /T /F | Out-Null
        $stopped = $true
        Write-Output "Backend stopped from port 8787 (PID $pidText)."
    }
}

if (-not $stopped) {
    Write-Output "Backend is not running."
}
