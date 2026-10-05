$ErrorActionPreference = 'Stop'
$taskPython = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'))
if (!(Test-Path -LiteralPath $taskPython)) { throw 'Missing project Python runtime' }
$listener = Get-NetTCPConnection -State Listen -LocalPort 8002 -ErrorAction SilentlyContinue
if ($listener) {
    $config = Invoke-RestMethod 'http://127.0.0.1:8002/api/machines'
    if ($config.config_version -ne 'yard-video-preview-v3') { throw 'Port 8002 is occupied by another service' }
    $state = Invoke-RestMethod 'http://127.0.0.1:8002/api/state'
    if ($state.auto_reclaim.version -eq 'rc01-auto-return-feed-v1') {
        Write-Output 'Video-preview service with RC01 automatic return/feed pilot is already running at http://127.0.0.1:8002'
        return
    }
    if (@($state.machines.PSObject.Properties.Value | Where-Object { $_.running -or $_.control }).Count -gt 0) {
        throw 'Preview machines have active motion or control; stop and release them before upgrading'
    }
    # Upgrade only the verified preview process, never an unrelated listener.
    $previewOwner = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $listener.OwningProcess)
    if (!$previewOwner -or $previewOwner.CommandLine -notlike '*uvicorn*yard_motion.preview:create_preview_app*--port 8002*') {
        throw 'Existing v3 service lacks the automatic pilot; stop that service manually before restarting'
    }
    Stop-Process -Id $listener.OwningProcess
}
$logFolder = Join-Path $PSScriptRoot 'data\video-preview-logs'
New-Item -ItemType Directory -Force -Path $logFolder | Out-Null
$process = Start-Process -FilePath $taskPython -ArgumentList @('-m','uvicorn','yard_motion.preview:create_preview_app','--factory','--host','127.0.0.1','--port','8002') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logFolder 'stdout.log') -RedirectStandardError (Join-Path $logFolder 'stderr.log') -PassThru
$process.Id | Set-Content (Join-Path $logFolder 'service.pid')
Write-Output ('Video-preview motion service started, PID ' + $process.Id)

