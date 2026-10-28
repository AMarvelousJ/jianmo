$ErrorActionPreference = 'Stop'
$taskPython = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'))
if (!(Test-Path -LiteralPath $taskPython)) { throw 'Missing project Python runtime' }
$listener = Get-NetTCPConnection -State Listen -LocalPort 8002 -ErrorAction SilentlyContinue
if ($listener) {
    $config = Invoke-RestMethod 'http://127.0.0.1:8002/api/machines'
    if ($config.config_version -eq 'yard-real-scale-preview-v1') {
        Write-Output 'Real-scale preview service is already running at http://127.0.0.1:8002'
        return
    }
    throw ('Port 8002 is occupied by ' + $config.config_version + '; stop that service before opening the real-scale preview')
}
$logFolder = Join-Path $PSScriptRoot 'data\real-scale-preview-logs'
New-Item -ItemType Directory -Force -Path $logFolder | Out-Null
$process = Start-Process -FilePath $taskPython -ArgumentList @('-m','uvicorn','yard_motion.preview:create_real_scale_preview_app','--factory','--host','127.0.0.1','--port','8002') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logFolder 'stdout.log') -RedirectStandardError (Join-Path $logFolder 'stderr.log') -PassThru
$process.Id | Set-Content (Join-Path $logFolder 'service.pid')
Write-Output ('Real-scale preview motion service started, PID ' + $process.Id)
