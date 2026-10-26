[CmdletBinding()]
param(
    [string]$NativeCodex,
    [string]$Runtime = (Join-Path $env:USERPROFILE '.codex\provider-routing-windows')
)
$ErrorActionPreference = 'Stop'
$path = Join-Path $Runtime 'windows.json'
$python = Join-Path $Runtime 'venv\Scripts\python.exe'
$package = Join-Path $Runtime 'venv\Lib\site-packages\codex_provider_routing'
Copy-Item -LiteralPath (Join-Path (Split-Path -Parent $PSScriptRoot) 'src\codex_provider_routing\catalog_refresh.py') -Destination $package
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'native_runtime.py') -Destination $Runtime
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'stdio_router.py') -Destination $Runtime
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'verify.py') -Destination $Runtime
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'code_mode_probe.py') -Destination $Runtime
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'start-app.ps1') -Destination $Runtime
$arguments = @((Join-Path $Runtime 'native_runtime.py'), '--settings', $path)
if ($NativeCodex) {
    $NativeCodex = (Resolve-Path -LiteralPath $NativeCodex).Path
    $arguments += @('--native', $NativeCodex)
}
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw 'Native runtime preparation failed. CLI override was not changed.' }
Write-Output 'Run windows/verify.py before restarting with the routing launcher.'
