from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from src.core.context import ContextManager, SessionInfo, project_root
from src.core.llm import LLM

SOUL_PATTERN = re.compile(r"<soul>\s*(.*?)\s*</soul>", re.DOTALL)


@dataclass(frozen=True)
class NonoReply:
    text: str
    soul_updated: bool = False
    workflow_name: str | None = None


class Nono:
    """Turns user text into a reply. First version has no tool loop."""

    def __init__(
        self,
        llm: LLM | None = None,
        context: ContextManager | None = None,
        workflow_dir: Path | None = None,
    ) -> None:
        self.llm = llm or LLM()
        self.context = context or ContextManager(self.llm)
        self.workflow_dir = workflow_dir or (project_root() / "src" / "workflows")

    def start(self) -> SessionInfo:
        return self.context.start()

    def create_session(self) -> SessionInfo:
        return self.context.create()

    def resume_session(self, name: str) -> SessionInfo:
        return self.context.resume(name)

    def list_sessions(self) -> list[SessionInfo]:
        return self.context.list_sessions()

    def reply(self, user_text: str) -> NonoReply:
        text = user_text.strip()
        if not text:
            return NonoReply(text="")

        workflow_name = self._maybe_load_workflow(text)
        self.context.add_message("user", text)
        raw = self.llm.complete(self.context.get_messages())
        visible, soul = _split_soul_update(raw)
        soul_updated = False
        if soul:
            self.context.update_soul(soul)
            soul_updated = True
        self.context.add_message("assistant", visible)
        return NonoReply(
            text=visible,
            soul_updated=soul_updated,
            workflow_name=workflow_name,
        )

    def _maybe_load_workflow(self, user_text: str) -> str | None:
        if "工作流" not in user_text or not self.workflow_dir.is_dir():
            return None
        for path in sorted(self.workflow_dir.glob("*.md")):
            name = path.stem
            if name and name in user_text:
                body = path.read_text(encoding="utf-8").strip()
                if not body:
                    return None
                self.context.add_message(
                    "system",
                    f"已加载工作流 {name}：\n{body}",
                )
                return name
        return None


def _split_soul_update(text: str) -> tuple[str, str | None]:
    match = SOUL_PATTERN.search(text)
    if not match:
        return text.strip(), None
    soul = match.group(1).strip()
    cleaned = SOUL_PATTERN.sub("", text).strip()
    return cleaned, soul or None
