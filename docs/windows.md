# Windows local Codex App

This page is for the **Windows local host**. For a Windows App connecting to WSL, install the [Linux / WSL service](linux-wsl.md) inside WSL instead. Installing one does not repair the other.

以下步骤针对 Windows 本机 App。连接到 WSL 的会话需要在 WSL 里安装另一套入口，两边互不代替。

## 1. Register the provider / 注册 provider

Preserve your existing top-level OpenAI model/default settings. Add the provider table to `%USERPROFILE%\.codex\config.toml`, with your own endpoint and provider ID:

```toml
[model_providers.local]
name = "Local Responses provider"
base_url = "http://127.0.0.1:8000/v1"
wire_api = "responses"
requires_openai_auth = false
supports_websockets = false
```

This is a loopback, unauthenticated example. Configure authentication if your endpoint requires it. Put API keys in the appropriate environment/credential mechanism, never in a public routes file. Supply truthful model metadata using the [official catalog format](https://learn.chatgpt.com/docs/model-catalogs). Keep root settings before the first TOML table.

保持原来的 OpenAI 默认。不要为了显示本地模型，把全局 `model_provider` 改成本地 provider；路由会只处理映射中的模型。模型目录只负责显示和能力描述，不负责修正错误的 provider。

Follow the [model selector guide](model-selector.md) ([中文](model-selector.zh-CN.md)) for a complete metadata example, combined OpenAI/custom catalog, reasoning controls, and refresh steps before installing the router.

## 2. Install / 安装

Requirements: Python 3.11+, the native Windows Codex CLI used by the App, and the .NET Framework compiler normally present on supported Windows installations. The Windows runtime uses only the Python standard library.

By default, installation discovers the installed `OpenAI.Codex` App package and snapshots its complete native runtime into the router's private directory. It does not pin a path under the App-managed `%LOCALAPPDATA%\OpenAI\Codex\bin\<hash>` cache: the App can rebuild or clean those directories.

In PowerShell, from the repository root:

```powershell
Copy-Item examples\routes.example.json routes.local.json
# Edit routes.local.json: use your actual served model IDs and registered provider ID.
.\windows\install.ps1 -Routes .\routes.local.json
python .\windows\verify.py --runtime "$env:USERPROFILE\.codex\provider-routing-windows"
```

For an unpackaged installation, pass `-NativeCodex 'C:\path\to\runtime\codex.exe'`. Its directory must contain the matching `codex-code-mode-host.exe`, `codex-command-runner.exe`, and `codex-windows-sandbox-setup.exe`; `rg.exe` and the sandbox service are copied when present. A lone executable is insufficient. The executable must be native, not another routing launcher. Installation refuses to overwrite an existing runtime directory.

For a non-default Codex directory, pass `-CodexHome 'C:\path\to\codex-home'`. The wrapper uses that directory for both routing metadata and native CLI configuration; an explicit `CODEX_HOME` in the launching environment takes precedence over the saved setting.

Verification checks the App's startup-policy JSON, custom-model start/resume, and the OpenAI default. It also executes a harmless real Code Mode cell through a scripted localhost Responses endpoint. No external model is called and no test shell command runs. All chats and configuration used by the probe are isolated.

Start with the process-scoped launcher in the next section. If you also want normal shortcuts to inherit the router, optional persistent activation is:

```powershell
.\windows\activate.ps1
```

Both activation and the launch helper run verification before setting an override. The optional `-Activate` installer switch performs persistent activation too.

## 3. Restart / 重启

**Fully exit Codex App**, including a remaining tray/background instance. Then, from the repository root:

```powershell
.\windows\start-app.ps1
```

This verifies the runtime and launches with `CODEX_CLI_PATH` only in the new App's environment. It restores the calling shell's earlier value afterward and does not set a Windows user variable. If the App is already running, it stops with an instruction to exit it; it never kills another instance.

Optional `activate.ps1` persists the user override and notifies Explorer. Existing App and shell processes retain their earlier environment. Prefer the process-scoped launcher until the real App has been checked after an upgrade.

不需要重启 Windows，也没有 Windows systemd 服务。必须完整退出 App 再启动，单独关掉一个窗口不一定会结束后台进程。当前会话正在运行时，先结束工作，再重启。

The helper detects the installed Store App. For an unpackaged installation, supply its executable:

```powershell
.\windows\start-app.ps1 -AppPath 'C:\path\to\ChatGPT.exe'
```

Create a new custom-model chat and ask for a short reply. Also select an OpenAI model and verify it still uses OpenAI. Restore an old custom-model chat after the restart. The startup wrapper corrects the lifecycle request; a thread already loaded under the wrong provider may need the full restart to clear its old state.

## Runtime files / 文件位置

Default runtime: `%USERPROFILE%\.codex\provider-routing-windows\`.

| File | Purpose |
| --- | --- |
| `codex-provider-routing.exe` | Launcher compiled locally from this repository |
| `stdio_router.py` | Windows JSONL routing transport |
| `native_runtime.py` | Installed-App discovery and complete native snapshots |
| `native\<digest>\` | Immutable native CLI and companion tools; old snapshots retained |
| `verify.py`, `code_mode_probe.py` | Startup, routing and local Code Mode checks |
| `venv\Lib\site-packages\codex_provider_routing\routing.py` | Shared routing rules |
| `windows.json` | Native CLI path, model map, previous override, local paths |

The App and native CLI binaries remain untouched. These generated files are local state, not files to publish. No prompt audit is enabled by the Windows installer.

## Upgrade / 升级

In App-package mode the wrapper rediscovers the installed package at startup. Changed native files produce a new private snapshot; existing snapshots are never cleaned while another process may use them. To upgrade an existing router's scripts and migrate an old cached CLI path:

```powershell
.\windows\update-native.ps1
python .\windows\verify.py --runtime "$env:USERPROFILE\.codex\provider-routing-windows"
.\windows\start-app.ps1
```

Fully exit the App before the last command. `update-native.ps1` backs up `windows.json`, checks native startup, and leaves `CODEX_CLI_PATH` unchanged. Use `-NativeCodex` for an explicit unpackaged source. Updating the Git checkout alone does not update an installed router.

The override remains an external integration. Future App protocols may change, so a real App launch is still needed after the isolated checks. If launch fails, fully exit and use a normal shortcut with the user/process override unset; do not copy individual helpers into an App-managed hash directory or change a hash by hand.

## Rollback / 撤回

Finish active work, fully exit the App, then run:

```powershell
.\windows\rollback.ps1
```

This restores the previous user `CODEX_CLI_PATH` value, notifies Explorer of the environment change, and leaves runtime files for inspection. Existing App and shell processes still have their earlier environment: relaunch from a refreshed Explorer or a shell whose `CODEX_CLI_PATH` has been restored. Avoid `start-app.ps1` after rollback because it explicitly enables routing for that launch. No config or chat record is restored/overwritten because the installer never changed those files.

## Troubleshooting / 排错

- Still seeing the ChatGPT account model error: check the App's newly spawned CLI process is `codex-provider-routing.exe`, the model ID matches `windows.json` exactly, and the App was fully exited before relaunch.
- New chats work but an old one fails: inspect its saved model and resume request. A loaded wrong-provider thread needs backend restart. Don't bulk-edit session databases.
- A tool or automatic review fails after the model replies: check the provider's actual request compatibility. Routing alone doesn't add tool or structured-output support.
- A native CLI upgrade breaks launch: update the real CLI path and run the isolated verification before restarting the App.
- Missing `codex-code-mode-host.exe`: migrate with `update-native.ps1`; verify the complete private snapshot before enabling the override.
- "Unable to load organization settings": check the startup-policy probe and actual native version first. This generic dialog can mask a CLI/runtime startup problem. Keep the override disabled while diagnosing.
