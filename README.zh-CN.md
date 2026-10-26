# Custom Model Provider in Codex App

让 Codex App 中指定的自定义模型自动使用正确的 provider，同时保留 OpenAI 默认。

支持[自动刷新官方模型目录](docs/catalog-refresh.md)，保留自定义模型和 Auto Review 配置，失败继续使用旧目录。Windows 和 WSL 各自启用。

有些版本的 App 选择自定义模型时，只发送模型名称，漏掉 `modelProvider`。模型即使已经显示在列表里，仍可能被交给默认的 OpenAI provider，报错：

> The model is not supported when using Codex with a ChatGPT account.

这个项目针对该问题提供兼容路由。模型目录负责模型说明和能力，provider 配置负责 API 地址和认证，路由负责把请求发给正确的 provider。三者需要分别配置。

| 场景 | 实现 | 说明 |
| --- | --- | --- |
| Windows 本机 App | 独立 stdio 包装入口 | [Windows 安装、重启、撤回](docs/windows.md) |
| Linux／WSL Remote | Unix WebSocket 路由用户服务 | [Linux／WSL 安装、服务管理、撤回](docs/linux-wsl.md) |

Windows 和 Linux／WSL 的代码及操作说明分开，共用模型路由规则与目录刷新逻辑。不修改 App 安装文件，不替换 Codex 二进制，不修改权限策略，不直接改聊天记录。它不能让不兼容的模型服务自动具备 Responses、工具调用、图像、结构化输出或自动审批审查能力。

需要在 **实际运行 app-server 的主机** 上注册 provider，并配置兼容的模型目录。使用独立的模型 ID，然后参考 `examples/routes.example.json` 填写映射。示例模型名称只是占位符。

把模型加入选择器、保留 OpenAI 列表、配置 reasoning 档位，以及更新目录的完整步骤见 [模型选择器教程](docs/model-selector.zh-CN.md)。仓库提供元数据示例和 `tools/merge_catalog.py` 合并工具。

可复用的 skill 位于 `skills/codex-app-custom-provider/`。复制到自己的 Codex skills 目录后，可以使用 `$codex-app-custom-provider` 协助配置和排错。

代码仓库仅包含通用源码、示例、文档和测试。安装生成的环境、运行状态、日志都应留在本机，不要提交到 Git。Linux 运行时保存的原生进程环境可能包含凭据，需要保持目录私有。

已验证的版本为 Windows CLI `0.164.0-alpha.11.1`、Linux／WSL CLI `0.163.0` 和 `0.164.0`。这是针对已观察行为的社区兼容方案，升级后需要重新检查，不能保证任意后续版本都兼容。

Windows 验证包含 App 启动配置、自定义模型的创建与恢复、OpenAI 默认，以及通过本地模拟 Responses 接口执行真实 Code Mode JavaScript。测试使用隔离配置，不调用外部模型。原生 CLI 和配套工具从已安装 App 生成完整的私有快照，避免依赖 App 可能清理的缓存目录；首次启用建议使用仅对该次 App 启动生效的入口。

详细原理见 [架构说明](docs/architecture.md)，英文入口见 [README](README.md)。
