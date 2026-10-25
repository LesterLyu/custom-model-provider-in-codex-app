# Add a model to the selector

[中文步骤](model-selector.zh-CN.md)

The selector needs **Codex model metadata**. Provider registration supplies the API address; this project's route map selects the provider. Complete all three steps. The installer doesn't generate a catalog automatically.

## 1. Prepare a custom model definition

```sh
cp examples/local-models.example.json local-models.local.json
```

In PowerShell, use `Copy-Item` instead of `cp` if preferred. Edit the copy for your actual model. If your provider already supplies a compatible full Codex catalog, use that instead of the example.

| Field | Meaning |
| --- | --- |
| `slug` | Exact model ID used by the API and route map |
| `display_name` | Label shown in the selector |
| `visibility` | `list` shows the entry; `hide` keeps an internal alias out of the normal list |
| `supported_in_api` | Match the actual provider capability; the example uses `true` |
| `supported_reasoning_levels` | Reasoning choices the model/provider actually accepts |
| `default_reasoning_level` | Default choice, included in the supported list |
| `context_window`, `max_context_window` | Actual context limits, not a way to enlarge the backend |
| `input_modalities`, tool-related fields | Actual image/tool support |

The example has a **placeholder ID**, text input, a 32K context, and three example reasoning choices. Replace those capabilities before using it for real inference. Its short instructions are an example too; use provider-tested instructions. It doesn't enable hosted search or automatic approval review.

Keep custom IDs distinct from hosted IDs. `slug`, inference `model`, and route-map key must match exactly.

## 2. Keep the OpenAI entries when building the catalog

This project uses a combined local catalog: existing hosted definitions plus custom definitions. A custom-only file would remove the hosted entries from that local catalog's list.

Choose a base **on the host running app-server**:

- A recent full catalog from your authorized upstream, or a current `models_cache.json` from that account.
- For an offline starting point, export the installed CLI's bundled metadata. It is a release snapshot, not a live account availability check.

The commands below use the bundled snapshot so they don't need API credentials. Substitute a fresh account/upstream catalog for `--base` when available.

**Windows PowerShell** — run from the repository root, using the real CLI path from the Windows setup:

```powershell
$nativeCodex = 'C:\path\to\native\codex.exe'
& $nativeCodex debug models --bundled | Set-Content bundled-models.local.json -Encoding UTF8
if ($LASTEXITCODE -ne 0) { throw 'Catalog export failed' }
$catalogHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
$catalogFile = Join-Path $catalogHome 'desktop.models.json'
python tools\merge_catalog.py --base bundled-models.local.json --extra local-models.local.json --output $catalogFile
```

**Linux / WSL** — run inside Linux from the repository root:

```sh
"$HOME/.local/bin/codex" debug models --bundled > bundled-models.local.json
catalog_home="${CODEX_HOME:-$HOME/.codex}"
python3 tools/merge_catalog.py --base bundled-models.local.json --extra local-models.local.json \
  --output "$catalog_home/desktop.models.json"
```

Substitute the actual native CLI path. If the output already exists, review it and add `--overwrite`; the tool saves a timestamped backup before replacing it. It rejects duplicate model IDs and never changes `config.toml`, auth, or defaults. It accepts a full `{"models": [...]}` response, the native cache wrapper, or a bundled array export. A plain OpenAI `{"data": [{"id": ...}]}` list isn't sufficient. Cache identity/etag fields aren't copied; model definitions are preserved.

## 3. Point the app-server host at the combined catalog

Back up that host's `config.toml`. Add or replace **one top-level** setting, before the first TOML table. Keep the existing OpenAI default model/provider.

Windows example — substitute the real absolute path; `%USERPROFILE%` isn't expanded inside TOML:

```toml
model_catalog_json = "C:/Users/YOUR_USER/.codex/desktop.models.json"
```

Linux / WSL example — substitute the actual Linux path; don't use a Windows path or literal `~`:

```toml
model_catalog_json = "/home/YOUR_USER/.codex/desktop.models.json"
```

For a custom `CODEX_HOME`, use that home for both the JSON file and config. Windows and WSL can run different CLI versions, so build/validate the catalog on each host separately.

## 4. Register the provider and map the ID

Use the provider table in the [Windows](windows.md#1-register-the-provider--注册-provider) or [Linux / WSL](linux-wsl.md#prepare--准备) guide. In the route map:

```json
{
  "routes": {
    "example-local-model": "local"
  }
}
```

Replace both identifiers with your actual model/provider. Before installation, edit `routes.local.json` and follow the platform installer.

For an **existing installation**, add the mapping alongside the existing entries in the installed runtime:

- Windows: the `routes` object in `%USERPROFILE%\.codex\provider-routing-windows\windows.json`.
- Linux / WSL: `~/.local/share/codex-provider-routing/routes.json` by default. Check the installed unit/state for custom or older manual installations.

Back up the runtime mapping before editing it. Editing the repository's example or `routes.local.json` alone doesn't update an already installed runtime. A catalog entry can make a model visible while a missing mapping still sends it to OpenAI.

## 5. Restart and verify

- Windows: fully exit the App, then run `windows/start-app.ps1` from the repository.
- Linux / WSL: disconnect the idle App, run `systemctl --user restart codex-provider-routing.service`, then reconnect.

Look for the custom `display_name` in the model selector. Confirm the reasoning choices, an OpenAI model still being listed, and a short custom-model reply. The example is metadata only; no inference server is included.

For a CLI metadata check without inference:

```powershell
# Windows: replace the native executable path.
& $nativeCodex debug models
```

```sh
# Linux / WSL: replace the native executable path if needed.
"$HOME/.local/bin/codex" debug models
```

Inspect the custom `slug`, `visibility`, and reasoning fields. The App consumes `model/list`; the example has also been checked through that RPC. A successful list/parse doesn't prove generation or tool support.

## Refresh and troubleshoot

- **OpenAI adds or changes models:** obtain a fresh base, reapply your separate custom definitions with the merge tool, and restart. The tool doesn't fetch or refresh automatically. A copied `models_cache.json` may be stale; check its timestamp/version and refresh with the normal OpenAI catalog active before using it as a new base. `debug models` with the local override active shows that override, not a newly fetched upstream list.
- **CLI upgrade:** export that CLI's updated bundled snapshot or fetch compatible account metadata, rebuild, and verify. Keep custom definitions separate so you don't hand-edit hosted instructions.
- **Dynamic catalogs:** use a trusted catalog gateway if you want server-managed refresh. Local `model_catalog_json` takes precedence over remote catalog discovery. A provider-scoped URL alone doesn't construct a combined OpenAI/custom selector. See the [official catalog reference](https://learn.chatgpt.com/docs/model-catalogs).
- **Entry absent:** check the active host, absolute file path, JSON parsing, `visibility`, current metadata/availability filters, and a full restart.
- **Entry visible, ChatGPT-account error on selection:** check the installed route map/provider and whether the routing entry point loaded.
- **Reasoning choices absent:** check the supported/default reasoning fields in the loaded catalog; don't advertise options the backend doesn't accept.

Generated catalogs can contain provider instructions or account-specific metadata. The repository ignores `*.local.json`; keep generated files/backups private, and don't commit your real `config.toml` or auth files.
