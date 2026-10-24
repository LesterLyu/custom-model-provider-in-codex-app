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
# Notify Explorer so future normal launches can inherit the updated user setting.
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class CodexEnvironmentNotice {
    [DllImport("user32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    public static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint msg, UIntPtr wParam,
        string lParam, uint flags, uint timeout, out UIntPtr result);
}
'@
$result = [UIntPtr]::Zero
[CodexEnvironmentNotice]::SendMessageTimeout([IntPtr]0xffff, 0x1a, [UIntPtr]::Zero, 'Environment', 2, 3000, [ref]$result) | Out-Null
Write-Output 'Activated. Fully exit Codex App and launch it with windows/start-app.ps1 once.'
