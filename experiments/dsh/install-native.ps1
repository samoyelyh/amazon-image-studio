$ErrorActionPreference='Stop'
$harness=Join-Path $PSScriptRoot 'harness'
New-Item -ItemType Directory -Path $harness -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'native-runtime-package.json') -Destination (Join-Path $harness 'package.json')
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'native-runtime-package-lock.json') -Destination (Join-Path $harness 'package-lock.json')
Push-Location $harness
try {& npm.cmd ci --ignore-scripts;if($LASTEXITCODE -ne 0){throw 'Pinned native Harness installation failed'}}finally{Pop-Location}
Write-Output 'Native Harness installed. No coding, shell or repository executor is enabled.'
