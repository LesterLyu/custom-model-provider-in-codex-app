# 把模型加入 Codex App 的选择器

[English / 完整命令](model-selector.md)

需要分别完成三件事：**模型目录决定显示什么；provider 定义 API 地址和认证；路由映射决定选中后发给谁。** 安装路由并不会自动生成模型目录。

## 1. 准备本地模型元数据

复制 `examples/local-models.example.json` 为 `local-models.local.json`，然后修改：

- `slug`：实际 API 模型 ID，必须和路由表的键一致。
- `display_name`：选择器显示名称。
- `visibility = "list"`：显示；内部审查别名等可以用 `"hide"`。
- `supported_reasoning_levels`：后端真正支持的档位。
- `default_reasoning_level`：默认档位，必须在支持列表中。
- 上下文、图像和工具能力：填写实际支持值，元数据不能扩大后端能力。

示例只是占位模型，默认写了文本输入、32K 上下文、low／medium／high 三档。不要直接当成你的模型规格。若服务端已提供完整的 Codex 模型目录，优先使用服务端定义。

### 工具模式：使用 `code_mode`

本配置为自定义模型选择 **`"tool_mode": "code_mode"`**：提供 JavaScript 的 `exec`／`wait` 编排入口，同时保留直接工具，便于检查模型和服务端的兼容性。保留 OpenAI 条目原来的模式。

这个字段写在**模型目录 JSON 的具体模型对象中**，不是 `config.toml` 的顶层设置。例如在 `local-models.local.json` 的自定义条目中添加：

```json
{
  "slug": "example-local-model",
  "tool_mode": "code_mode"
}
```

以上只是完整模型定义的片段；仓库的元数据示例已包含此字段。

| 值 | 提供给模型的工具 |
| --- | --- |
| `"direct"` | 直接提供普通工具，例如 `exec_command`、`apply_patch`。 |
| `"code_mode"` | 提供 JS 编排入口，也保留直接工具；JS 中通过 `tools.*` 调用内部工具。 |
| `"code_mode_only"` | 大部分工具经 JS 调用；部分特殊工具仍可能直接提供。 |
| `null` 或省略 | 不显式覆盖；实际模式取决于模型默认值及 feature 设置。 |

这些工具定义已在 **Codex CLI 0.164.0** 上通过隔离的本地模拟 Responses 接口核对，没有调用真实模型。这只能确认客户端提供什么工具，不能证明任意模型都能正确使用。Code Mode 还需要可用的 host／runtime，以及后端兼容的工具调用格式；CLI 升级后应重新验证。

**Windows 和 WSL 分别配置**：修改各自主配置 `model_catalog_json` 指向的目录。若 profile 指向另一个目录，也要更新其中对应的自定义条目。将此字段保存在单独的自定义定义中，后续重新合并目录时才能保留；不要依赖直接修改托管的 `models_cache.json`。

修改前先备份。Windows 完整退出并重新启动 App；WSL 在会话空闲时断开 App，执行 `systemctl --user restart codex-provider-routing.service` 后重新连接。只更新磁盘上的 CLI，不会替换已经运行的 app-server。

这个模式只改变工具调用方式。浏览器、MCP 仍须在实际主机上安装、启用并连通；它不会自动把 Windows 内置浏览器接给 WSL。在 JS 中只返回筛选后的内容，可以减少进入模型上下文的输出，但不代表执行日志完全不记录原始结果。

## 2. 合并 OpenAI 列表，避免只剩本地模型

保留当前 OpenAI 模型定义，再追加本地模型。仓库提供 `tools/merge_catalog.py`，不会修改原有模型条目、默认配置或认证；不会把缓存顶层的身份字段复制到结果中。

Windows PowerShell，在仓库根目录运行：

```powershell
$nativeCodex = 'C:\path\to\native\codex.exe'
& $nativeCodex debug models --bundled | Set-Content bundled-models.local.json -Encoding UTF8
if ($LASTEXITCODE -ne 0) { throw 'Catalog export failed' }
$catalogHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
python tools\merge_catalog.py --base bundled-models.local.json --extra local-models.local.json --output (Join-Path $catalogHome 'desktop.models.json')
```

WSL／Linux，在 Linux 内的仓库根目录运行：

```sh
"$HOME/.local/bin/codex" debug models --bundled > bundled-models.local.json
catalog_home="${CODEX_HOME:-$HOME/.codex}"
python3 tools/merge_catalog.py --base bundled-models.local.json --extra local-models.local.json \
  --output "$catalog_home/desktop.models.json"
```

把 CLI 路径换成实际原生程序。目标文件已经存在时，检查后加 `--overwrite`，工具会先保存带时间戳的备份。

`--bundled` 是该 CLI 版本内置的离线快照，不代表账号实时可用列表。已有新鲜的账号 `models_cache.json` 或上游完整目录时，用它替换 `--base`。普通 `/v1/models` 只有 ID 的列表不够。

## 3. 在对应主机的主配置中指定目录

先备份 `config.toml`。在第一个 TOML 表之前添加或替换唯一一行，路径换成真实绝对路径：

```toml
# Windows 示例
model_catalog_json = "C:/Users/YOUR_USER/.codex/desktop.models.json"
```

```toml
# WSL 示例
model_catalog_json = "/home/YOUR_USER/.codex/desktop.models.json"
```

保留原来的 OpenAI 默认 `model`／`model_provider`。TOML 中不要写未展开的 `%USERPROFILE%` 或 `~`。Remote 到 WSL 就改 WSL 配置；Windows 本机就改 Windows 配置。两边 CLI 版本可能不同，应分别生成并验证。

## 4. 配置 provider 和运行时路由

参照 [Windows](windows.md) 或 [Linux／WSL](linux-wsl.md) 文档注册 provider。路由条目例如：

```json
"example-local-model": "local"
```

左边是模型 ID，右边是已注册的 provider ID。

新安装：填写 `routes.local.json` 后安装。已经安装：备份后，将新条目加入实际运行时映射：

- Windows：`%USERPROFILE%\.codex\provider-routing-windows\windows.json` 的 `routes` 对象。
- Linux／WSL：默认 `~/.local/share/codex-provider-routing/routes.json`；旧的手工安装请以实际 unit／脚本为准。

只改仓库里的示例或 `routes.local.json`，不会自动更新现有安装。目录有模型但路由缺失，仍可能报 ChatGPT account 不支持该模型。

## 5. 重启并验证

Windows 完整退出 App，再运行仓库中的 `windows/start-app.ps1`。WSL 在空闲时断开 App，然后执行：

```sh
systemctl --user restart codex-provider-routing.service
```

重新连接后，检查模型名称、reasoning 档位、OpenAI 模型是否仍在，最后发一条简短消息验证实际推理。`codex debug models` 可以检查当前载入的元数据，但模型能列出来不等于后端能够对话或调用工具。

## OpenAI 更新列表怎么办

Windows 和 WSL 均支持[启动时自动刷新](catalog-refresh.md)：保留单独的自定义配置，获取官方最新目录，经原生 CLI 校验后替换；失败沿用旧目录。首次需要启用，并列出所有自定义条目，包括隐藏的 Auto Review。下面的手工合并方式仍然可用。

合并工具不会自动联网更新。获取新鲜的上游／账号目录后重新合并、重启即可；自定义条目单独保存在 `local-models.local.json`，不必反复修改 OpenAI 定义。

注意：启用本地目录覆盖时，`debug models` 显示的是该目录；已有缓存也可能过期。要以账号缓存为新基底，需要在正常 OpenAI 模型发现生效时刷新它，并检查时间、CLI 版本。CLI 升级后，也要重新验证元数据格式。

如果需要自动刷新，可由可信网关提供合并目录。本地 `model_catalog_json` 会优先于远程目录发现；只给本地 provider 加一个 URL，并不等于把它自动并入 OpenAI 默认选择器。见 [官方目录说明](https://learn.chatgpt.com/docs/model-catalogs)。

真实目录、缓存、配置和备份都留在本机，不要提交到公开仓库。
