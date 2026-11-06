param([switch]$ReuseAuthorizedProvider, [switch]$ControllersOnly, [int]$Workers=4,
    [ValidateSet('kimi-for-coding','gpt-6.1-terra','gpt-6.1-sol')][string]$MainModel='kimi-for-coding',
    [ValidateSet('kimi-for-coding','gpt-6.1-terra','gpt-6.1-sol')][string]$ExecutorModel='kimi-for-coding',
    [ValidateSet('kimi-for-coding','gpt-6.1-terra','gpt-6.1-sol')][string]$VisionModel='kimi-for-coding')
$ErrorActionPreference='Stop'
$env:PYTHONUTF8='1'
$experimentRoot=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$python=Join-Path (Split-Path $experimentRoot -Parent) 'AI生图/server/.venv/Scripts/python.exe'
$state=Join-Path $PSScriptRoot '.state'
if(Test-Path -LiteralPath (Join-Path $state 'processes.json')){
    $recorded=Get-Content -LiteralPath (Join-Path $state 'processes.json') -Raw | ConvertFrom-Json
    foreach($entry in $recorded){if($ControllersOnly -and $entry.role -like 'worker-*'){continue};if(Get-Process -Id $entry.id -ErrorAction SilentlyContinue){throw 'Experiment processes are already running. Use stop.ps1 first.'}}
}
New-Item -ItemType Directory -Path $state -Force | Out-Null
if(@(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object LocalPort -in @(18870,18871)).Count){throw 'Experiment ports are already occupied; existing processes were not changed.'}
Push-Location (Join-Path $experimentRoot 'server')
try {
    $bootArgs=@('-m','app.experiments.dsh.bootstrap')
    if($ReuseAuthorizedProvider){$bootArgs+='--reuse-authorized-provider'}
    if(-not $ControllersOnly){& $python @bootArgs;if($LASTEXITCODE -ne 0){throw 'Isolated bootstrap failed'}}
    $container=docker ps -a --filter 'name=^ais-dsh-experiment-redis$' --format '{{.Names}}'
    if(-not $container){docker run -d --name ais-dsh-experiment-redis --label ais.experiment=dsh -p 127.0.0.1:16489:6379 redis:7.4-alpine redis-server --appendonly yes | Out-Null}
    else {docker start ais-dsh-experiment-redis | Out-Null}
    $processes=@()
    if($ControllersOnly){$processes=@($recorded | Where-Object role -like 'worker-*')}
    $env:DSH_INTERNAL_TOKEN=(Get-Content -LiteralPath (Join-Path $state 'sidecar.token') -Raw).Trim()
    $env:DSH_STATE_DIR=Join-Path $state 'core'
    $env:DSH_MAIN_MODEL=$MainModel
    $env:DSH_EXECUTOR_MODEL=$ExecutorModel
    $env:DSH_VISION_MODEL=$VisionModel
    $sidecar=Start-Process -FilePath (Get-Command node.exe).Source -ArgumentList @('--experimental-transform-types',('"'+(Join-Path $PSScriptRoot 'sidecar.ts')+'"')) -WorkingDirectory $experimentRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $state 'sidecar.log') -RedirectStandardError (Join-Path $state 'sidecar.err.log')
    Remove-Item Env:DSH_INTERNAL_TOKEN
    Remove-Item Env:DSH_STATE_DIR
    Remove-Item Env:DSH_MAIN_MODEL
    Remove-Item Env:DSH_EXECUTOR_MODEL
    Remove-Item Env:DSH_VISION_MODEL
    $processes+=@{id=$sidecar.Id;role='sidecar'}
    $api=Start-Process -FilePath $python -ArgumentList @('-m','uvicorn','app.experiments.dsh.api:create_app','--factory','--host','127.0.0.1','--port','18870') -WorkingDirectory (Join-Path $experimentRoot 'server') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $state 'api.log') -RedirectStandardError (Join-Path $state 'api.err.log')
    $processes+=@{id=$api.Id;role='api'}
    for($i=1;$i -le $(if($ControllersOnly){0}else{$Workers});$i++){
        $worker=Start-Process -FilePath $python -ArgumentList @('-m','app.experiments.dsh.worker',[string]$i) -WorkingDirectory (Join-Path $experimentRoot 'server') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $state "worker-$i.log") -RedirectStandardError (Join-Path $state "worker-$i.err.log")
        $processes+=@{id=$worker.Id;role="worker-$i"}
    }
    $processes | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $state 'processes.json')
    $ready=$false
    for($attempt=0;$attempt -lt 20;$attempt++){
        try{
            $apiHealth=Invoke-RestMethod 'http://127.0.0.1:18870/health' -TimeoutSec 1
            $coreHealth=Invoke-RestMethod 'http://127.0.0.1:18871/health' -TimeoutSec 1 -Headers @{'x-dsh-token'=(Get-Content -LiteralPath (Join-Path $state 'sidecar.token') -Raw).Trim()}
            if($apiHealth.status -eq 'ok' -and $coreHealth.status -eq 'ok'){$ready=$true;break}
        }catch{}
        Start-Sleep -Milliseconds 500
    }
    if(-not $ready){throw 'Experiment API/Sidecar did not become ready; inspect .state logs. Processes are preserved for diagnosis.'}
    Write-Output 'Experiment: http://127.0.0.1:18870/experiment'
    Write-Output "Local experiment login is in $state/login.json."
} finally {Pop-Location}
