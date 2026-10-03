"""The update_soul tool: one LLM call decides whether soul.md should change."""

from __future__ import annotations

from src.core.context import ContextManager
from src.core.llm import LLM

KEEP = "KEEP"

_PROMPT = """\
你是 Nono 的人格守护者。根据下面的新内容，判断 Nono 的人格设定是否需要更新。

只有当新内容包含应当长期遵守的自我约束或人格调整时才更新\
（例如用户明确要求 Nono 以后以某种方式行事）；普通对话、一次性请求都不要更新。

- 不需要更新：只回答 {keep}
- 需要更新：输出完整的新人格全文（不是差异），包在 <soul>...</soul> 中，此外不要输出任何内容。

当前人格：
{soul}

新内容：
{content}"""


def update_soul(content: str, llm: LLM, context: ContextManager) -> bool:
    """Decide via one LLM call whether ``content`` warrants a soul.md update.

    Args:
        content: The new material to judge.
        llm: Chat client used for the judgement call.
        context: Provides the current soul and receives the rewrite.

    Returns:
        True when soul.md was rewritten.
    """
    text = content.strip()
    if not text:
        return False
    prompt = _PROMPT.format(keep=KEEP, soul=context.read_soul(), content=text)
    answer = llm.chat(prompt).strip()
    soul = _extract_soul(answer)
    if soul is None:
        # KEEP, an empty answer, or a reply without a usable tag all mean no change.
        return False
    context.update_soul(soul)
    return True


def _extract_soul(answer: str) -> str | None:
    """Pull the full new persona out of ``<soul>...</soul>``, if present."""
    open_index = answer.find("<soul>")
    close_index = answer.find("</soul>")
    if open_index < 0 or close_index <= open_index:
        return None
    soul = answer[open_index + len("<soul>") : close_index].strip()
    return soul or None
