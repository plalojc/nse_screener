$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
& cmd /c (Join-Path $scriptDir "start_backend.cmd")
exit $LASTEXITCODE
