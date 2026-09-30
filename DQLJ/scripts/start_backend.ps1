param([int]$Port = 8001)
$projectRoot = Split-Path $PSScriptRoot -Parent
$sharedPython = Join-Path (Split-Path $projectRoot -Parent) '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $sharedPython)) { throw 'Python environment missing. Install the project dependencies first.' }
Push-Location $projectRoot
try { & $sharedPython -m uvicorn yard_motion.api:app --host 127.0.0.1 --port $Port --no-access-log }
finally { Pop-Location }
