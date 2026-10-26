# Platform procedures

The maintained implementation is at https://github.com/LesterLyu/custom-model-provider-in-codex-app. Inspect that checkout and its platform documentation rather than inventing flags or socket layouts. Tested baseline: Windows CLI 0.164.0-alpha.11.1 and Linux/WSL CLI 0.163.0 and 0.164.0; revalidate after upgrades.

## Windows local App

Code: `windows/`. Guide: https://github.com/LesterLyu/custom-model-provider-in-codex-app/blob/main/docs/windows.md

- Verify that the App launches a stdio app server and recognizes `CODEX_CLI_PATH` in the installed version.
- Install the independent launcher with a private model map, without activation. Prefer installed-App discovery and a complete private native runtime snapshot; never pin the App's hashed relocation cache. An explicit unpackaged source must contain the matching companion tools.
- Run `windows/verify.py` for startup-policy, routing and actual Code Mode execution against a localhost mock. Then fully exit the App and launch with `windows/start-app.ps1`, whose override applies only to that launch. Keep persistent activation optional until a real App launch has succeeded.
- The wrapper changes only incoming lifecycle JSONL messages. Other CLI subcommands delegate to the real CLI. Avoid wrapping back to itself.
- Migrate existing installs with `windows/update-native.ps1`, verify, and restart. App-package mode follows the installed package and retains prior private snapshots. `windows/rollback.ps1` restores the previous user override; it doesn't modify model config or sessions.

## Linux / WSL remote

Code: Unix modules in `src/codex_provider_routing/`. Guide: https://github.com/LesterLyu/custom-model-provider-in-codex-app/blob/main/docs/linux-wsl.md

- Install on the remote host, preserve its existing defaults, and register the provider there. Windows-only config paths aren't usable in Linux.
- Derive the canonical socket from the owned native control alias. The router must bind the canonical endpoint and hold its lifetime `.lock`; binding only the friendly alias can be bypassed by the App.
- `codex app-server proxy` is a raw byte tunnel carrying a WebSocket HTTP Upgrade and frames. It isn't a JSONL endpoint. Verify through that actual tunnel, not only with a direct socket client.
- Don't hold the native startup lock while launching the private backend. Never stop every Codex process by name. Installation should refuse unfamiliar layouts and active work.
- Service commands, run on Linux as the owning user:

```sh
systemctl --user restart codex-provider-routing.service
systemctl --user status codex-provider-routing.service
journalctl --user -u codex-provider-routing.service -n 50
```

Disconnect idle App clients before maintenance. Unit paths/runtime locations vary for earlier manual installs; read the installed unit before updating it. `loginctl enable-linger` concerns the Linux user manager, not Windows boot or automatic startup of a stopped WSL distribution.

## Provider and catalog references

For selector setup, use https://github.com/LesterLyu/custom-model-provider-in-codex-app/blob/main/docs/model-selector.md (Chinese version: `model-selector.zh-CN.md` in the same directory).

- Preserve the existing hosted definitions when creating a combined local catalog. Use full, version-compatible metadata; a plain ID list isn't enough.
- Match `slug` to the API model and route key. Check `display_name`, `visibility`, and truthful supported/default reasoning levels.
- `tools/merge_catalog.py` combines a fresh base with separate custom definitions and backs up an existing output when `--overwrite` is given. It doesn't fetch upstream data or edit config/auth.
- For automatic startup refresh, follow `docs/catalog-refresh.md`. Enable separately on each host and explicitly retain every custom ID, including hidden review aliases. Keep generated `provider-catalog/` files private. Verify failures preserve the old catalog and permit startup; restart only when work is idle.
- Set one top-level `model_catalog_json` absolute path on the actual app-server host. Update the installed runtime map as well; editing an installation input file doesn't update existing routing state.
- Restart and check `model/list`, then a short authorized inference. Keep generated catalogs private. The repository's example capabilities are placeholders, not a guarantee about any model.

- https://learn.chatgpt.com/docs/config-file/config-advanced
- https://learn.chatgpt.com/docs/model-catalogs
- https://learn.chatgpt.com/docs/app-server
- https://learn.chatgpt.com/docs/web-search

Keep catalog entries truthful, especially tool/vision/reasoning support. Preserve a refresh strategy for hosted model metadata when using a combined catalog; don't freeze an old OpenAI list indefinitely. Never publish actual catalogs containing private instructions or local account details.
