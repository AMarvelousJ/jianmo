param(
    [string]$BindAddress = "127.0.0.1",
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$RepositoryRoot = Split-Path -Parent $ProjectRoot
$PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $PythonPath)) {
    $PythonPath = Join-Path $RepositoryRoot ".venv\Scripts\python.exe"
}
$LogDirectory = Join-Path $RepositoryRoot "logs"
$StdoutLog = Join-Path $LogDirectory "unity-backend.out.log"
$StderrLog = Join-Path $LogDirectory "unity-backend.err.log"

if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "Python virtual environment not found: $PythonPath"
}

New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null

$Existing = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
if ($Existing) {
    Write-Host "SL15 backend is already listening at http://${BindAddress}:$Port/"
    exit 0
}

$Process = Start-Process `
    -FilePath $PythonPath `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", $BindAddress, "--port", $Port `
    -WorkingDirectory $ProjectRoot `
    -RedirectStandardOutput $StdoutLog `
    -RedirectStandardError $StderrLog `
    -WindowStyle Hidden `
    -PassThru

$Deadline = (Get-Date).AddSeconds(10)
do {
    try {
        $Health = Invoke-RestMethod -Uri "http://${BindAddress}:$Port/health" -TimeoutSec 1
        if ($Health.status -eq "ok") {
            $Listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
                Select-Object -First 1
            Write-Host "SL15 backend started. PID=$($Listener.OwningProcess), URL=http://${BindAddress}:$Port/"
            exit 0
        }
    }
    catch {
        Start-Sleep -Milliseconds 200
    }
} while ((Get-Date) -lt $Deadline -and -not $Process.HasExited)

if (Test-Path -LiteralPath $StderrLog) {
    Get-Content -LiteralPath $StderrLog -Tail 30
}
throw "SL15 backend failed to become ready within 10 seconds."
