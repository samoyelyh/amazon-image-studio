param([switch]$ControllerOnly)
$ErrorActionPreference='Stop'
$state=Join-Path $PSScriptRoot '.state'
$recorded=Get-Content -LiteralPath (Join-Path $state 'processes.json') -Raw | ConvertFrom-Json
if(-not $ControllerOnly){
    $experimentRoot=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
    $python=Join-Path (Split-Path $experimentRoot -Parent) 'AI生图/server/.venv/Scripts/python.exe'
    & $python -c 'import sqlite3,sys; d=sqlite3.connect(sys.argv[1]); n=d.execute("SELECT count(*) FROM jobs WHERE status IN (''running'',''dispatching'')").fetchone()[0]; print("Active experiment jobs:",n); sys.exit(2 if n else 0)' (Join-Path $state 'platform.sqlite')
    if($LASTEXITCODE -ne 0){throw 'Active jobs exist; leave Workers running. ControllerOnly is safe for controller recovery.'}
}
foreach($entry in $recorded){
    if($ControllerOnly -and $entry.role -like 'worker-*'){continue}
    $process=Get-CimInstance Win32_Process -Filter "ProcessId=$($entry.id)" -ErrorAction SilentlyContinue
    if(-not $process){continue}
    $allowed=$process.CommandLine -like '*app.experiments.dsh.*' -or $process.CommandLine.Contains((Join-Path $PSScriptRoot 'sidecar.ts'))
    if(-not $allowed){throw "Recorded PID $($entry.id) no longer belongs to this experiment; refusing to stop it."}
    # Windows venv launchers can own a second python.exe. Verify and stop only
    # descendants with this experiment's module/path before stopping the launcher.
    $children=Get-CimInstance Win32_Process -Filter "ParentProcessId=$($entry.id)"
    foreach($child in $children){
        if($child.Name -eq 'conhost.exe'){continue}
        $childCommand=[string]$child.CommandLine
        $childAllowed=$childCommand -like '*app.experiments.dsh.*' -or $childCommand.Contains((Join-Path $PSScriptRoot 'sidecar.ts'))
        if(-not $childAllowed){throw "Unexpected child $($child.ProcessId); refusing to interrupt it."}
        Stop-Process -Id $child.ProcessId -ErrorAction SilentlyContinue
    }
    Stop-Process -Id $entry.id -ErrorAction SilentlyContinue
}
foreach($port in @(18870,18871)){
    foreach($connection in @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)){
        $remaining=Get-CimInstance Win32_Process -Filter "ProcessId=$($connection.OwningProcess)"
        $remainingCommand=[string]$remaining.CommandLine
        $owned=$remainingCommand -like '*app.experiments.dsh.api:create_app*' -or $remainingCommand.Contains((Join-Path $PSScriptRoot 'sidecar.ts'))
        if(-not $owned){throw "Port $port belongs to another process; it was not stopped."}
        Stop-Process -Id $connection.OwningProcess -ErrorAction SilentlyContinue
    }
}
Write-Output 'Stopped selected experiment processes; data and Redis are preserved.'
