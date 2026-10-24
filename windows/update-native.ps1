[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$NativeCodex,
    [string]$Runtime = (Join-Path $env:USERPROFILE '.codex\provider-routing-windows')
)
$ErrorActionPreference = 'Stop'
$NativeCodex = (Resolve-Path -LiteralPath $NativeCodex).Path
$path = Join-Path $Runtime 'windows.json'
$settings = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
if ($NativeCodex -eq $settings.launcher) { throw 'The native CLI cannot be the routing launcher.' }
& $NativeCodex --version
if ($LASTEXITCODE -ne 0) { throw 'Native CLI version check failed.' }
Copy-Item -LiteralPath $path -Destination ($path + '.before-native-update-' + (Get-Date -Format 'yyyyMMddHHmmss'))
$settings.codex = $NativeCodex
$settings | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $path -Encoding UTF8
Write-Output 'Native path updated. Run windows/verify.py, then fully restart the App.'
