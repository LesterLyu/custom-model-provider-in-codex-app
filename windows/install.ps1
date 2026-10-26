[CmdletBinding()]
param(
    [string]$NativeCodex,
    [Parameter(Mandatory=$true)][string]$Routes,
    [string]$Runtime = (Join-Path $env:USERPROFILE '.codex\provider-routing-windows'),
    [string]$CodexHome = $(if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }),
    [string]$Python = 'python',
    [switch]$Activate
)
$ErrorActionPreference = 'Stop'
if ($NativeCodex) { $NativeCodex = (Resolve-Path -LiteralPath $NativeCodex).Path }
$Routes = (Resolve-Path -LiteralPath $Routes).Path
$Runtime = [IO.Path]::GetFullPath($Runtime)
$CodexHome = (Resolve-Path -LiteralPath $CodexHome).Path
$repo = Split-Path -Parent $PSScriptRoot
$map = Get-Content -LiteralPath $Routes -Raw | ConvertFrom-Json
if (-not $map.routes -or -not @($map.routes.PSObject.Properties).Count) { throw 'A nonempty routes object is required.' }
foreach ($route in $map.routes.PSObject.Properties) {
    if (-not $route.Name.Trim() -or $route.Value -isnot [string] -or -not $route.Value.Trim() -or $route.Value -eq 'openai') {
        throw 'Use distinct model IDs mapped to custom providers.'
    }
}
if (Test-Path -LiteralPath $Runtime) { throw 'Runtime already exists. Review or remove the previous installation before reinstalling.' }
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw '.NET Framework C# compiler not found.' }
New-Item -ItemType Directory -Path $Runtime | Out-Null
& $Python -m venv (Join-Path $Runtime 'venv')
if ($LASTEXITCODE -ne 0) { throw 'Python venv creation failed.' }
$package = Join-Path $Runtime 'venv\Lib\site-packages\codex_provider_routing'
New-Item -ItemType Directory -Path $package | Out-Null
foreach ($name in @('__init__.py', 'routing.py', 'catalog_refresh.py')) {
    Copy-Item -LiteralPath (Join-Path $repo "src\codex_provider_routing\$name") -Destination $package
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'stdio_router.py') -Destination $Runtime
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'native_runtime.py') -Destination $Runtime
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'verify.py') -Destination $Runtime
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'code_mode_probe.py') -Destination $Runtime
$launcher = Join-Path $Runtime 'codex-provider-routing.exe'
& $compiler /nologo /target:exe "/out:$launcher" (Join-Path $PSScriptRoot 'CodexProviderLauncher.cs')
if ($LASTEXITCODE -ne 0) { throw 'Launcher compilation failed.' }
$settings = @{
    codex = $NativeCodex; home = $CodexHome; launcher = $launcher; routes = $map.routes
    previous_override = [Environment]::GetEnvironmentVariable('CODEX_CLI_PATH', 'User')
}
$settings | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $Runtime 'windows.json') -Encoding UTF8
& (Join-Path $PSScriptRoot 'update-native.ps1') -Runtime $Runtime -NativeCodex $NativeCodex
& $launcher --version
if ($LASTEXITCODE -ne 0) { throw 'Native CLI delegation failed.' }
Write-Output "Installed Windows runtime: $Runtime"
if ($Activate) {
    & (Join-Path $PSScriptRoot 'activate.ps1') -Runtime $Runtime
} else {
    Write-Output 'Not activated. Verify first, then activate CODEX_CLI_PATH as documented.'
}
