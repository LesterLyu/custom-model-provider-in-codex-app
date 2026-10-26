# Linux / WSL remote Codex App

Install this on the Linux host running the remote app server. Windows local chats use the separate [Windows wrapper](windows.md).

此页适用于 Linux／WSL Remote。Windows 本机会话的入口与此不同，请看 Windows 文档。

## Prepare / 准备

Requirements: Linux or WSL2, Python 3.11+, a running systemd **user** manager, and a working native Codex CLI. For WSL, enable systemd using the distribution's supported setup first. The installer deliberately supports only the native command/socket layouts it recognizes.

1. Register the custom provider in the **remote** `~/.codex/config.toml`. Preserve OpenAI defaults.
2. Supply a compatible model catalog on that host. A Windows file path won't work inside Linux.
3. Connect from the App once so Codex creates its native control socket, then disconnect when idle.

Example provider table:

```toml
[model_providers.local]
name = "Local Responses provider"
base_url = "http://127.0.0.1:8000/v1"
wire_api = "responses"
requires_openai_auth = false
supports_websockets = false
```

Use the real reachable address and authentication for your environment. Loopback inside WSL may not refer to the Windows host, depending on WSL networking. Check connectivity separately. No provider/profile/catalog is rewritten by this installer.

Follow the [model selector guide](model-selector.md) ([中文](model-selector.zh-CN.md)) inside Linux to build the combined catalog, configure its absolute Linux path, and retain OpenAI selector entries.

## Install / 安装

Clone this repository and install in a dedicated user virtual environment:

```sh
git clone https://github.com/LesterLyu/custom-model-provider-in-codex-app.git
cd custom-model-provider-in-codex-app
python3 -m venv "$HOME/.local/share/codex-provider-routing-venv"
"$HOME/.local/share/codex-provider-routing-venv/bin/pip" install .
cp examples/routes.example.json routes.local.json
# Edit routes.local.json with exact model IDs and registered provider IDs.
```

Run a read-only preflight; pass the stable native CLI path explicitly:

```sh
"$HOME/.local/share/codex-provider-routing-venv/bin/codex-provider-routing" install \
  --routes routes.local.json --codex "$HOME/.local/bin/codex"
```

It checks the schema, owned canonical socket, exact native process, provider registration, and loaded thread status. If the native command/layout is unfamiliar, it stops before replacing anything. Close/disconnect the App to avoid new work during the switch. Then apply:

```sh
"$HOME/.local/share/codex-provider-routing-venv/bin/codex-provider-routing" install \
  --routes routes.local.json --codex "$HOME/.local/bin/codex" --apply
```

If your CLI lives elsewhere, substitute its actual path. The installer saves the original native environment privately, stops only that owned idle daemon, starts and enables the user service, and verifies the real `codex app-server proxy` byte path. Existing installations are never overwritten automatically.

Reconnecting the App still uses the normal SSH/proxy entry. No SSH command wrapper or CLI binary patch is needed: the router owns the native public socket.

On reboot the service recreates its private directory under `/tmp` and holds the native startup lock before launching its backend. If the App started a native fallback first, the service verifies its user, executable, launch arguments, working directory and Codex home. It waits for loaded work to finish, then gracefully stops that exact idle process and restores routing with the saved environment. Unknown listeners and unreadable thread status are preserved; they are never treated as idle. A Linux pidfd prevents signaling a recycled PID. Transient startup failures keep retrying rather than hitting systemd's short start limit.

## User service commands / 用户服务命令

**Restart / 重启** — finish active turns and disconnect the App first:

```sh
systemctl --user restart codex-provider-routing.service
```

**Status / 状态**:

```sh
systemctl --user status codex-provider-routing.service
systemctl --user show codex-provider-routing.service -p MainPID -p NRestarts -p ActiveState
```

**Logs / 日志**:

```sh
journalctl --user -u codex-provider-routing.service -n 50
journalctl --user -u codex-provider-routing.service -f
```

**Start / stop / enable / disable**:

```sh
systemctl --user start codex-provider-routing.service
systemctl --user stop codex-provider-routing.service
systemctl --user enable codex-provider-routing.service
systemctl --user disable codex-provider-routing.service
```

这些命令不用 sudo。停止路由后 App 可能自行启动原生 daemon，所以维护期间先断开 App。`stop` 只停止当前服务，`disable` 只取消自动启动，二者不是完整撤回。

Optionally keep the user manager running after SSH logout:

```sh
loginctl show-user "$USER" -p Linger
# Administrative action, only when wanted for this account:
sudo loginctl enable-linger "$USER"
```

Linger keeps the user manager alive while the Linux host is running. It doesn't start a stopped WSL distribution or arrange Windows boot startup.

## Locations / 文件位置

| Item | Default location |
| --- | --- |
| User unit | `~/.config/systemd/user/codex-provider-routing.service` |
| Private runtime/state | `~/.local/share/codex-provider-routing/` |
| Public alias | `~/.codex/app-server-control/app-server-control.sock` |
| Canonical endpoint | Derived from the actual native alias under `/tmp/codex-daemon-<uid>/` |
| Private backend alias | `~/.codex/app-server-control/app-server-routing-native.sock` |

Custom `XDG_CONFIG_HOME`, `CODEX_HOME`, `--home`, and `--root` can change these. Global `--home` / `--root` options go **before** the command. Earlier manually installed versions can use another runtime directory; check `systemctl --user cat codex-provider-routing.service` for the actual paths. Do not overwrite an existing unit with a second installation.

Runtime directory mode is 0700 and generated JSON files are 0600. `native-environment.json` may contain credentials from the original daemon; never commit, share, or paste it. The root Codex config stays unchanged. Optional `--audit` writes model/provider/method metadata, without prompts, request IDs, or thread IDs.

## Verify and upgrade / 验证与升级

```sh
"$HOME/.local/share/codex-provider-routing-venv/bin/codex-provider-routing" doctor
"$HOME/.local/share/codex-provider-routing-venv/bin/codex-provider-routing" verify --model example-local-model
```

Replace the example model ID with an installed mapping. Both commands first confirm the service is active and its MainPID owns the public socket, so a native fallback cannot be mistaken for the router. `doctor` then checks schema and actual proxy connectivity; `verify --model` also creates an ephemeral mapped-provider thread without inference. Neither sends a chat message. Reconnect the App and make a short real request to check generation.

After updating the native CLI, disconnect the App, restart the user service, and rerun `doctor`/`verify`. A stable native CLI symlink lets the service use the updated binary after restart. If its path changes, inspect the private installation state and update deliberately. Schema compatibility alone doesn't establish compatibility with future native socket or App changes.

To update the router package itself, reinstall the reviewed checkout into the dedicated venv, disconnect the App, restart, and verify. Don't overwrite an unrelated unit or assume an older manually installed script uses this package.

Units generated before startup recovery was added also need `StartLimitIntervalSec=0` in their `[Unit]` section. Apply this to the existing owned unit (or a user unit drop-in), run `systemctl --user daemon-reload`, then restart when loaded work is idle. Updating the Python package alone does not regenerate an existing service unit.

## Rollback / 撤回

With the App disconnected and loaded threads idle:

```sh
"$HOME/.local/share/codex-provider-routing-venv/bin/codex-provider-routing" rollback
```

This disables/stops routing and restores the original native launch with its captured environment. Unit/runtime files remain for review. It never restores an old root config or rewrites sessions. It refuses to interrupt an active thread or replace an active native daemon.

If the routing service is broken, inspect the journal and stop it before recovery; don't kill all Codex processes. An App/native fallback may already be listening on the public endpoint. The rollback command refuses ambiguous active endpoints rather than taking over another process. Keep the saved runtime private while diagnosing.
