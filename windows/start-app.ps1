[CmdletBinding()]
param(
    [string]$Runtime = (Join-Path $env:USERPROFILE '.codex\provider-routing-windows'),
    [string]$AppPath
)
$ErrorActionPreference = 'Stop'
$launcher = Join-Path $Runtime 'codex-provider-routing.exe'
if (-not (Test-Path -LiteralPath $launcher)) { throw 'Routing launcher not found.' }
if (-not $AppPath) {
    $package = Get-AppxPackage -Name OpenAI.Codex | Select-Object -First 1
    if (-not $package) { throw 'Specify -AppPath for an unpackaged Codex App.' }
    $AppPath = Join-Path $package.InstallLocation 'app\ChatGPT.exe'
}
$env:CODEX_CLI_PATH = $launcher
Start-Process -FilePath $AppPath -WindowStyle Hidden
