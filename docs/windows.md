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

## 2. Install / 安装

Requirements: Python 3.11+, the native Windows Codex CLI used by the App, and the .NET Framework compiler normally present on supported Windows installations. The Windows runtime uses only the Python standard library.

In PowerShell, from the repository root:

```powershell
Copy-Item examples\routes.example.json routes.local.json
# Edit routes.local.json: use your actual served model IDs and registered provider ID.
$nativeCodex = (Get-Command codex).Source
.\windows\install.ps1 -NativeCodex $nativeCodex -Routes .\routes.local.json
python .\windows\verify.py --runtime "$env:USERPROFILE\.codex\provider-routing-windows"
```

The native executable must be the real `codex.exe`, not this project's wrapper. If `Get-Command` selects another installation, pass the correct absolute path explicitly. Installation refuses to overwrite an existing runtime directory.

For a non-default Codex directory, pass `-CodexHome 'C:\path\to\codex-home'`. The wrapper uses that directory for both routing metadata and native CLI configuration; an explicit `CODEX_HOME` in the launching environment takes precedence over the saved setting.

The verification starts two isolated stdio app servers, checks custom-model start/resume and the OpenAI default, and leaves defaults unchanged. It does not perform model inference. After that, activate:

```powershell
.\windows\activate.ps1
```

The optional `-Activate` installer switch can also set the user override, but separate verification first is easier to review.

## 3. Restart / 重启

**Fully exit Codex App**, including a remaining tray/background instance. Then, from the repository root:

```powershell
.\windows\start-app.ps1
```

This explicitly launches with the routing override. The activation script also saves `CODEX_CLI_PATH` as a Windows **user** environment variable and notifies Explorer, so subsequent normal launches can inherit it. An existing App process or terminal keeps its old environment. If an ordinary shortcut still ignores the override, use the explicit launch command or sign out/in to refresh the Windows environment.

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
| `venv\Lib\site-packages\codex_provider_routing\routing.py` | Shared routing rules |
| `windows.json` | Native CLI path, model map, previous override, local paths |

The App and native CLI binaries remain untouched. These generated files are local state, not files to publish. No prompt audit is enabled by the Windows installer.

## Upgrade / 升级

App or CLI updates can change the native binary's path. Point the runtime to the newly installed real CLI, verify, then restart:

```powershell
.\windows\update-native.ps1 -NativeCodex 'C:\path\to\new\codex.exe'
python .\windows\verify.py --runtime "$env:USERPROFILE\.codex\provider-routing-windows"
.\windows\start-app.ps1
```

Fully exit the old App before the last command. The wrapper is external, so updating Codex doesn't overwrite it. Compatibility still needs checking: future App versions may change how `CODEX_CLI_PATH` or provider fields work. The installer copies scripts into the runtime, so updating this Git checkout alone does not update an existing runtime.

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
