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
$AppPath = (Resolve-Path -LiteralPath $AppPath).Path
$appName = [IO.Path]::GetFileNameWithoutExtension($AppPath)
if (Get-Process -Name $appName -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $AppPath }) {
    throw 'Codex App is already running. Finish work and fully exit it before starting the routed instance.'
}
& (Join-Path $Runtime 'venv\Scripts\python.exe') (Join-Path $Runtime 'verify.py') --runtime $Runtime
if ($LASTEXITCODE -ne 0) { throw 'Routing verification failed. App was not launched and CODEX_CLI_PATH was not changed.' }
$previous = [Environment]::GetEnvironmentVariable('CODEX_CLI_PATH', 'Process')
try {
    $env:CODEX_CLI_PATH = $launcher
    Start-Process -FilePath $AppPath -WindowStyle Hidden
} finally {
    if ($null -eq $previous) { Remove-Item Env:CODEX_CLI_PATH -ErrorAction SilentlyContinue }
    else { $env:CODEX_CLI_PATH = $previous }
}
