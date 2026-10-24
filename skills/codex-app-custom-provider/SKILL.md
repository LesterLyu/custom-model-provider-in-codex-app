---
name: codex-app-custom-provider
description: Configure or troubleshoot custom model providers in Codex App on Windows local hosts or Linux/WSL remote hosts, including wrong-provider model errors, model catalogs, and selective routing while preserving OpenAI defaults.
---

# Codex App custom providers

Use this skill when a custom model is visible but can't start/resume, the App sends it through OpenAI, or the user requests coexistence of custom and OpenAI models. Repository: https://github.com/LesterLyu/custom-model-provider-in-codex-app

## Diagnose before choosing a fix

1. Identify the host actually running app-server: Windows local and WSL Remote are separate installations. Record native CLI and desktop App versions.
2. Inspect effective model/provider settings on that host without printing secrets. A CLI profile that works interactively may not be loaded by an App connection.
3. Check provider registration, reachable API, and compatible model metadata separately. A model catalog describes capabilities; it doesn't guarantee provider routing or implement tools.
4. For the ChatGPT-account unsupported-model error, verify the lifecycle request or server result actually selected OpenAI. Don't assume every error with a custom model has this cause.
5. Preserve the user's default model/provider and approval policy. Never route a hosted model name unless the user intentionally wants all requests with that exact name redirected.

## Apply a scoped compatibility layer

Read [the platform procedures](references/platforms.md) for the relevant host. Prefer native supported configuration when it works. If the observed App version omits or misselects `modelProvider`, use the repository's exact model-to-provider mapping on `thread/start`, `thread/resume`, and `thread/fork`.

Windows uses the `windows/` stdio launcher selected through `CODEX_CLI_PATH`. Linux/WSL uses the `src/codex_provider_routing/` Unix WebSocket service. Don't install one in place of the other or replace the native binary. Keep runtime secrets and state outside a public checkout.

Prepare and verify before switching the running App. A reconnect/restart can interrupt a turn: use the user's existing authorization and current activity to choose timing. A loaded thread may retain its old provider until the backend restarts.

## Verify the outcome

Check the actual App transport, explicit OpenAI selection, custom model selection, resume, and a short real reply when authorized. Isolated no-inference checks establish routing, not generation/tool compatibility. Test reasoning controls, image input, structured output, and automatic review only as needed for the user's task; don't advertise unsupported capabilities.

Hosted web search, MCP search tools, and tool discovery are different. A search flag alone doesn't implement provider search. Report tested versions, what was changed, and the exact restart/rollback commands. Never paste auth files, process environment snapshots, session databases, or private logs into an issue or public repo.
