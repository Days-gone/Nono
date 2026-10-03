# Nono
你的小助手，一款相信基座模型的力量的Agent！

# 设计哲学
我们相信基座模型的力量，只提供最简单的约束和脚手架。

主要构成部分：

- core: 
  LLM:主要包含了对不同API的封装使得 LLM provider 在这一层得到统一封装，目前只兼容openai API格式。
  Nono:主要负责对工具的迭代调用的逻辑进行处理，集成其他的模块如Tool，Workflow等。
- Tool:
  工具包, 负责为Nono提供一些能力，只单纯的提供某一个工具并做好, 目前提供 bash、update_soul 与 workflow（列出/加载）工具，后续的工具包视情况添加。
- Workflow: 
  工作流，当前运行目录的 `.workflows/<名称>/` 即一个工作流。其中 `workflow.md` 是说明书，加载时注入上下文；`scripts/` 存放该工作流的工具脚本（stdlib 优先、非交互、参数走命令行），不注入上下文，由模型经 bash 工具按需调用。由它们内部构成工作流以方便用户间快速的完成某个任务的传递。
- ContextManager:
  用来管理上下文的构成和从磁盘加载历史记录，为Nono的重要组成部分，由他来负责Nono每次的回话管理和人格维护等功能。

# 更新历史

2026.8.16
实现来一个最简单版本，将会话历史由本地的.history/xxx.jsonl进行管理。

2026.9.23
CLI 支持流式输出与 Markdown 渲染，回复边生成边渲染；非终端环境自动退回纯文本。
新增桌宠：输入行上方多出一个 Block，球形身体、一对长条眼睛的小 Nono 在其中生活——会眨眼、认真听你打字、答完开心、出错委屈、久无动静还会打瞌睡（`--no-pet` 可关闭）。

2026.10.3
新增 update_soul 工具（`src/tools/`）：输入一段内容，由一次 LLM 调用判断是否需要改写 `configs/soul.md`——回答 `KEEP` 则不动，返回包在 `<soul>...</soul>` 中的完整新人格则落盘。
新增 tests/：只覆盖关键组件——流式 soul 标签过滤 `SoulFilter`、增量 Markdown 块切分、update_soul 工具（`uv run pytest` 运行）。
Nono 集成工具：update_soul 与 workflow 工具挂载为 Nono 的方法；工作流改为显式 `/workflow` 命令——`/workflow` 列出当前目录 `.workflows/` 下的工作流，`/workflow <名称>` 将该目录内的 md 文件按文件名顺序注入上下文（取代原先按关键词嗅探 `src/workflows/*.md` 的临时方案）。
新增 `/tools` 命令：列出当前可用的工具，工具清单由 `src/tools/` 的 `TOOLS` 注册表统一维护。
新增 bash 工具与 `/bash <命令>` 命令：只读命令（ls/cat/grep/git status 等白名单）直接放行，含重定向、命令替换、sudo 或白名单外命令的一律先询问许可；分类是保守的朴素解析，宁可多问。该工具依赖 PATH 上的 bash（Windows 下用 Git Bash），Windows 平台暂未覆盖其测试。
Nono 支持工具调用循环：模型现在可以在回复中通过 function calling 调用 bash 工具（流式），写命令仍会先询问用户，工具结果写回上下文后继续对话，最多 8 轮；CLI 会展示每次工具调用及结果预览。至此"对工具的迭代调用"落地。
新增首个工作流 `duanju`（AI 短剧创作），并确立工作流目录结构：`workflow.md` 为注入上下文的说明书（立项→剧本→角色设定→分镜→合成提示词→生成→ffmpeg 拼接），`scripts/` 为模型经 bash 调用的工具脚本（`init_project.py` 脚手架、`make_prompts.py` 角色设定+分镜合成逐镜头提示词、`concat.sh` 片段拼接）。
