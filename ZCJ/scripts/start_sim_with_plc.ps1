param(
    [string]$PlcIp = "10.60.97.40",
    [int]$PlcSlot = 0,
    [int]$WebPort = 8765
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$repositoryRoot = Split-Path -Parent $projectRoot
$projectPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $projectPython)) {
    $projectPython = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
}

if (-not (Test-Path -LiteralPath $projectPython)) {
    throw "Python virtual environment was not found at $projectPython"
}

$env:SL15_PLC_ENABLED = "true"
$env:SL15_PLC_IP = $PlcIp
$env:SL15_PLC_SLOT = [string]$PlcSlot
$env:SL15_PLC_SYNC_INTERVAL_S = "0.1"
$env:SL15_PLC_TIMEOUT_S = "2.0"
$env:SL15_PLC_RECONNECT_INTERVAL_S = "2.0"
$env:SL15_PLC_STALE_AFTER_S = "0.5"

Set-Location -LiteralPath $projectRoot
& $projectPython -m uvicorn app.main:app --host 0.0.0.0 --port $WebPort
