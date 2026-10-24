[CmdletBinding()]
param([string]$Runtime = (Join-Path $env:USERPROFILE '.codex\provider-routing-windows'))
$ErrorActionPreference = 'Stop'
$settings = Get-Content -LiteralPath (Join-Path $Runtime 'windows.json') -Raw | ConvertFrom-Json
$current = [Environment]::GetEnvironmentVariable('CODEX_CLI_PATH', 'User')
if ($current -ne $settings.launcher) { throw 'The override changed since installation; review it instead of overwriting.' }
[Environment]::SetEnvironmentVariable('CODEX_CLI_PATH', $settings.previous_override, 'User')
$env:CODEX_CLI_PATH = $settings.previous_override
Write-Output 'Previous override restored. Fully exit and relaunch Codex App. Runtime retained; no config or sessions changed.'
