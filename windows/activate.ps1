[CmdletBinding()]
param([string]$Runtime = (Join-Path $env:USERPROFILE '.codex\provider-routing-windows'))
$ErrorActionPreference = 'Stop'
$settings = Get-Content -LiteralPath (Join-Path $Runtime 'windows.json') -Raw | ConvertFrom-Json
$current = [Environment]::GetEnvironmentVariable('CODEX_CLI_PATH', 'User')
if ($current -ne $settings.previous_override -and $current -ne $settings.launcher) {
    throw 'The user override changed since installation; review it first.'
}
& $settings.launcher --version
if ($LASTEXITCODE -ne 0) { throw 'Native CLI delegation failed.' }
[Environment]::SetEnvironmentVariable('CODEX_CLI_PATH', $settings.launcher, 'User')
$env:CODEX_CLI_PATH = $settings.launcher
. (Join-Path $PSScriptRoot 'environment.ps1')
Send-CodexEnvironmentChanged
Write-Output 'Activated. Fully exit Codex App and launch it with windows/start-app.ps1 once.'
