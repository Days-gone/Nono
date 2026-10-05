"""Nono's tool package: each tool does one thing well; TOOLS is what users see."""

from __future__ import annotations

from dataclasses import dataclass

from src.tools.bash import BASH_SCHEMA, BashResult, is_readonly, run_bash
from src.tools.update_soul import update_soul
from src.tools.workflow import list_workflows, load_workflow

__all__ = [
    "BASH_SCHEMA",
    "BashResult",
    "TOOLS",
    "ToolInfo",
    "is_readonly",
    "list_workflows",
    "load_workflow",
    "run_bash",
    "update_soul",
]


@dataclass(frozen=True)
class ToolInfo:
    """One tool as users see it: a name, what it does, and who can trigger it.

    ``model_callable`` marks the tools the model may request on its own
    (declared to the API as function schemas). The rest exist only as slash
    commands the user types -- the model has no way to invoke them.
    """

    name: str
    help: str
    model_callable: bool = False


# Single source of truth for the tool list shown by the CLI's /tools command.
# Only bash is exposed to the model; see Nono._TOOL_SCHEMAS.
TOOLS: tuple[ToolInfo, ...] = (
    ToolInfo("bash", "执行 bash 命令：只读命令直接放行，写命令先询问许可", model_callable=True),
    ToolInfo("update_soul", "输入一段内容，由一次 LLM 调用判断是否更新 configs/soul.md 人格设定"),
    ToolInfo("workflow", "列出或加载当前目录 .workflows/<名称>/ 中的工作流"),
)
