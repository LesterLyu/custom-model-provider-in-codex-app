# Platform procedures

The maintained implementation is at https://github.com/LesterLyu/custom-model-provider-in-codex-app. Inspect that checkout and its platform documentation rather than inventing flags or socket layouts. Tested baseline: Windows CLI 0.164.0-alpha.11.1 and Linux/WSL CLI 0.163.0; revalidate after upgrades.

## Windows local App

Code: `windows/`. Guide: https://github.com/LesterLyu/custom-model-provider-in-codex-app/blob/main/docs/windows.md

- Verify that the App launches a stdio app server and recognizes `CODEX_CLI_PATH` in the installed version.
- Install the independent launcher with the real native CLI path and a private model map; first use the installer without activation. Run `windows/verify.py` in its isolated home.
- Activate the Windows user override, fully exit the App, and explicitly launch using `windows/start-app.ps1` once. Existing Windows processes retain their earlier environment. User environment changes alone don't alter the running App.
- The wrapper changes only incoming lifecycle JSONL messages. Other CLI subcommands delegate to the real CLI. Avoid wrapping back to itself.
- Upgrade the saved native CLI path when necessary, verify, and restart. `windows/rollback.ps1` restores the previous user override; it doesn't modify model config or sessions.

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

- https://learn.chatgpt.com/docs/config-file/config-advanced
- https://learn.chatgpt.com/docs/model-catalogs
- https://learn.chatgpt.com/docs/app-server
- https://learn.chatgpt.com/docs/web-search

Keep catalog entries truthful, especially tool/vision/reasoning support. Preserve a refresh strategy for hosted model metadata when using a combined catalog; don't freeze an old OpenAI list indefinitely. Never publish actual catalogs containing private instructions or local account details.
