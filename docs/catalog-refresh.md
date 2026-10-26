# Automatic catalog refresh / 自动刷新模型目录

Windows and Linux/WSL routers can refresh the combined local catalog before starting native app-server. OpenAI definitions come from the authenticated official Codex catalog for the native CLI version. Custom definitions are merged unchanged, including reasoning, instructions, visibility and tool settings. Defaults, providers and approval policy are not modified.

Update the installed router code first. A working combined `model_catalog_json` must exist in user-level `config.toml`. Enable once, listing **every custom ID** to retain, including hidden review aliases and entries absent from the routing map. Substitute actual IDs and paths.

Windows:

```powershell
$runtime = Join-Path $env:USERPROFILE '.codex\provider-routing-windows'
$settings = Get-Content (Join-Path $runtime 'windows.json') -Raw | ConvertFrom-Json
& (Join-Path $runtime 'venv\Scripts\python.exe') -m codex_provider_routing.catalog_refresh `
  --home $settings.home --enable --model example-local-model --model example-review `
  --codex $settings.codex --force
```

Linux/WSL, using the router's own virtual environment:

```sh
"$HOME/.local/share/codex-provider-routing-venv/bin/python" \
  -m codex_provider_routing.catalog_refresh --home "$HOME/.codex" \
  --enable --model example-local-model --model example-review \
  --codex "$HOME/.local/bin/codex" --force
```

Earlier manual installs may use another virtual environment/launcher; update that entry point too. Both maintained entry points call this module. An unconfigured home does nothing. For later manual refreshes omit `--enable` and `--model`; `--force` ignores freshness. Re-enabling refuses to overwrite existing custom definitions.

Windows refreshes only on real stdio app-server startup, not version/help/debug/startup-policy queries. WSL refreshes after claiming the startup lock and before starting its private backend. The native CLI parses each candidate in an isolated home before atomic replacement. Duplicate/colliding IDs, malformed responses, concurrent edits, network/login/validation/replacement failures keep the old catalog and startup continues. Diagnostics use stderr; no credentials, response bodies or instructions are logged. No inference is requested.

Windows 和 WSL 分别启用。新列表在下次后端启动加载：Windows 完整退出 App 后从路由入口启动；WSL 在空闲、断开 App 后重启用户服务。刷新器不会自行中断会话，也不是定时任务。

Private files under `<CODEX_HOME>/provider-catalog/`:

| File | Purpose |
| --- | --- |
| `settings.json` | Absolute output catalog path, interval, network timeout |
| `custom.json` | Preserved custom definitions; edit this for future custom-model changes |
| `original.json` / `previous.json` | Initial catalog / catalog before latest replacement |
| `state.json` | Identity/version/content fingerprints and freshness; no credentials |
| `refresh.lock` | OS lock, released automatically on exit |

Default interval: 3600 seconds; network timeout: 10 seconds. A shorter upstream `max-age` wins. `no-cache`/`no-store` disables freshness reuse, fetching again at the next backend start; generated local configuration remains for the requested offline fallback. Identity, version or file edits invalidate freshness.

Authentication uses existing file-backed `auth.json` (ChatGPT access token/account ID or saved OpenAI API key). Credentials go only to the fixed official HTTPS endpoint; redirects are rejected. Login renewal and OS-keyring-only credentials are not implemented here. Maintain login with Codex normally; missing/expired credentials keep the old catalog. Windows delegation also resolves configured provider `env_key` names from the user environment when missing in the process; existing process values take precedence.

To disable, rename `settings.json` while no refresh is running. The current catalog continues working. To undo a catalog change, restore `previous.json` or `original.json` to the configured output path, then restart the backend when idle. Disabling does not remove mappings or change defaults. Keep all generated files/backups private; metadata does not grant model access. [Official model catalog reference](https://learn.chatgpt.com/docs/model-catalogs).
