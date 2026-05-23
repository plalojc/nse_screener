$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
& cmd /c (Join-Path $scriptDir "stop_frontend.cmd")
exit $LASTEXITCODE
