# Custom Model Provider in Codex App

Keep OpenAI as the default while selected custom models use their own provider in Codex App.

When the App sends a custom model ID without `modelProvider`, the app server can select the default OpenAI provider and report **“The model is not supported when using Codex with a ChatGPT account.”** Registering a provider and adding a model to the catalog are necessary, but do not repair that request. This project supplies a small compatibility router for that case.

[中文说明](README.zh-CN.md) · [Model selector](docs/model-selector.md) · [Automatic catalog refresh](docs/catalog-refresh.md) · [Windows setup](docs/windows.md) · [Linux / WSL setup](docs/linux-wsl.md) · [Architecture](docs/architecture.md)

## Platforms

| Host running Codex | Implementation | Tested native CLI |
| --- | --- | --- |
| Windows local App | JSONL stdio wrapper, selected through `CODEX_CLI_PATH` | 0.164.0-alpha.11.1 |
| Linux / WSL remote | Unix WebSocket router with a systemd user service | 0.163.0, 0.164.0 |

This is a community workaround for observed versions, not an official Codex feature or a guarantee about future App internals. It does not patch App resources, replace Codex binaries, implement a model API, or bypass account entitlements. You still need a working custom provider endpoint.

## Start here

1. Register your custom provider on the computer running the app server and follow the [model selector guide](docs/model-selector.md) to add compatible metadata while retaining the OpenAI entries.
2. Give custom models distinct IDs and create a model-to-provider map using [the example](examples/routes.example.json). Use real IDs served by your provider; the example names are placeholders.
3. Follow the **platform-specific** installation and verification instructions linked above.
4. Reconnect or fully restart the App as described there. Verify the selected provider and a short real reply before relying on it.

The router changes only `thread/start`, `thread/resume`, and `thread/fork` requests for exact mapped model IDs. It preserves approval policy, reasoning effort, prompts, and unrelated traffic. A model explicitly selected in a request takes precedence over saved thread metadata. For a resume without a model, it can read the newest `state_*.sqlite` database in read-only mode. It never edits session files or that database.

Provider registration, model catalogs, and routing have separate jobs. Consult the official [provider configuration](https://learn.chatgpt.com/docs/config-file/config-advanced) and [model catalog specification](https://learn.chatgpt.com/docs/model-catalogs) for your installed version. A plain `/v1/models` list doesn't supply all Codex model capabilities.

## Repository layout

```text
windows/                         Windows installer, launcher, stdio router, verification
src/codex_provider_routing/
  routing.py                     Shared, platform-independent routing rules
  catalog_refresh.py             Shared startup refresh with custom-model preservation
  router.py                      Linux / WSL Unix WebSocket transport
  manage.py                      Linux / WSL installer and lifecycle checks
  rpc.py                         Unix control / native proxy verification client
docs/windows.md                  Windows install, restart, upgrade, rollback
docs/linux-wsl.md                Linux / WSL install, user service, restart, rollback
docs/model-selector.md           Catalog merge, selector entries, reasoning choices, refresh
skills/codex-app-custom-provider/ Reusable Codex troubleshooting skill
tests/                           Isolated routing, transport, and file-safety tests
```

## Skill

Copy `skills/codex-app-custom-provider` into your Codex skills directory, normally `~/.codex/skills/`, on the host where you want to use it. Invoke `$codex-app-custom-provider`, or let Codex select it for a matching setup or troubleshooting task. The skill covers both platforms and preserves the user's chosen default provider and permission settings.

## Validation and privacy

On Linux / WSL, install into a temporary virtual environment and run:

```sh
python -m pip install '.[test]'
python -m unittest discover -s tests -v
python -m build
# Optional: actual installed CLI; isolated CODEX_HOME; no model inference.
python tools/verify_native.py --codex /absolute/path/to/codex
```

Windows has a separate `windows/verify.py` check. Native checks use temporary homes and preserve defaults. Windows checks startup policy, a synthetic resume fixture, and a real Code Mode cell through a scripted localhost Responses endpoint; no external model is called. Linux uses ephemeral threads with an unreachable inference endpoint. These checks do not prove that a particular model server can generate, use tools, or handle automatic approval review; test those separately with the user's authorization.

Source and examples contain no user configuration, credentials, prompts, session IDs, production addresses, native environment snapshots, or binaries. Installation generates private local runtime files. Linux may save the native process environment, including secrets, to preserve authentication: keep that runtime directory private and never upload it. Routing audit is off by default and records only model/provider/method metadata when enabled.

## Web search

Hosted `web_search`, MCP search servers, and tool discovery (`tool_search`) are different facilities. Adding a model catalog flag or setting `web_search = "live"` doesn't implement search in a custom model server. Advertise only capabilities the provider actually supports. See [official web search guidance](https://learn.chatgpt.com/docs/web-search).

License: [MIT](LICENSE).
