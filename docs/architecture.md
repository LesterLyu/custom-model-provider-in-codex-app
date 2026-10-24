# Architecture and compatibility boundaries

## Routing decision

For `thread/start`, `thread/resume`, and `thread/fork`:

1. Prefer an explicit `params.model`, then `params.config.model`.
2. If absent on resume/fork, read the saved model from the newest `state_*.sqlite`, read-only.
3. If the exact model ID is mapped, set `params.modelProvider` to the configured provider and make the model explicit. Correct an existing nested `config.model_provider` too.
4. Preserve all other fields. Pass unmapped traffic through unchanged, including explicit OpenAI model selections.

Model IDs in the map must be unique to the custom provider. Mapping a shared hosted model name would also redirect hosted requests with that name. The installer rejects mapping the effective default model to help preserve the default.

An already loaded thread may ignore a resume provider override. Restarting the app server clears that loaded state; changing only a database field or catalog entry isn't a reliable fix. A model switch inside an already loaded conversation should be checked separately. These routers don't rewrite `turn/start` or invent a provider-switch field for it.

## Windows local App

```text
Codex App -> CODEX_CLI_PATH launcher -> stdio_router.py -> native codex app-server
                                      JSONL rewrite       unchanged native binary
```

The desktop App version tested here recognizes `CODEX_CLI_PATH`. A small C# launcher exposes a normal executable entry point and forwards raw streams to Python. UTF-8 input must omit a BOM; .NET Framework's default encoding can otherwise invalidate the first JSONL request. Every write is flushed to avoid delaying small RPCs.

Only stdio app-server invocations are routed. Other CLI commands, including schema generation, version checks, and remote proxy commands, delegate to the real CLI. The real executable is stored separately to prevent recursive launching. No Windows systemd service is involved.

## Linux / WSL remote

```text
App -> SSH -> codex app-server proxy -> canonical Unix socket / router
                                       -> private native Unix socket -> native app-server
```

The proxy is a raw byte tunnel. WebSocket HTTP Upgrade and masked WebSocket frames travel across it; sending JSONL directly to `app-server proxy` is incorrect. This differs from the Windows local stdio connection. The native transport is documented in the [official App Server reference](https://learn.chatgpt.com/docs/app-server).

The friendly control socket is a symlink to the native canonical endpoint under `/tmp/codex-daemon-<uid>/`. The router binds the canonical endpoint and owns `<endpoint>.lock` for its entire lifetime. Binding only the friendly alias lets the App bypass the router or start another native daemon. The installer derives and validates the actual path rather than guessing its hash.

The backend listens on a different private socket. Forwarded WebSocket headers retain authentication metadata, while hop-by-hop headers and the previous WebSocket handshake headers are regenerated. Ordinary HTTP control/health GET responses are relayed too.

Never hold `app-server-startup.lock` while launching the native backend: it can deadlock startup. Cleanup removes only owned, inactive sockets or validated native socket aliases, including dangling symlinks. It never kills other Codex/IDE processes by name.

## Upgrades and capabilities

CLI upgrades shouldn't overwrite these external scripts. The native binary path, socket layout, provider selection, and App override behavior can still change. Schema checks establish that routing fields exist; only the actual App connection and a real short inference establish usable integration.

Reasoning controls come from compatible model metadata and provider support. Automatic approval review additionally needs its own supported model request format; routing a model doesn't implement structured output. Preserve approval policy and test review separately when requested.

Web search isn't supplied by either router. MCP searches execute through their tools; OpenAI hosted search requires compatible server/runtime support. `tool_search` discovers tools and isn't itself a web search engine.
