$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
& (Join-Path $scriptDir "stop_frontend.ps1")
& (Join-Path $scriptDir "stop_backend.ps1")
