"""Session context: jsonl history on disk, message assembly, and soul.md upkeep."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from src.core.llm import LLM

HISTORY_DIR_NAME = ".history"
SESSION_NAME_FORMAT = "%Y%m%d-%H%M%S"
RECENT_MESSAGE_LIMIT = 50
BUILTIN_SOUL = "你是 Nono，一个相信基座模型力量的小助手。用简洁、直接的中文帮助用户。"


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class SessionInfo:
    name: str
    path: Path


class ContextManager:
    """Builds model context, keeps jsonl history, and maintains soul.md."""

    def __init__(
        self,
        llm: LLM,
        history_dir: Path | None = None,
        soul_path: Path | None = None,
    ) -> None:
        self._llm = llm
        self.history_dir = history_dir or (Path.cwd() / HISTORY_DIR_NAME)
        self.soul_path = soul_path or (project_root() / "configs" / "soul.md")
        self.session_name = ""
        self.session_path: Path | None = None
        self._messages: list[dict[str, Any]] = []
        self._summary: str | None = None
        self._summary_upto = 0
        self.history_dir.mkdir(parents=True, exist_ok=True)

    def start(self) -> SessionInfo:
        sessions = self.list_sessions()
        if sessions:
            return self.resume(sessions[0].name)
        return self.create()

    def create(self) -> SessionInfo:
        base = datetime.now().strftime(SESSION_NAME_FORMAT)
        name = base
        path = self.history_dir / f"{name}.jsonl"
        # Two sessions in the same second would otherwise share a file.
        counter = 1
        while path.exists():
            name = f"{base}-{counter}"
            path = self.history_dir / f"{name}.jsonl"
            counter += 1
        path.touch()
        self.session_name = name
        self.session_path = path
        self._messages = []
        self._summary = None
        self._summary_upto = 0
        return SessionInfo(name=name, path=path)

    def resume(self, name: str) -> SessionInfo:
        path = self.history_dir / f"{name}.jsonl"
        if not path.is_file():
            raise FileNotFoundError(f"session not found: {name}")
        self.session_name = name
        self.session_path = path
        self._messages = self._read_jsonl(path)
        self._load_summary()
        return SessionInfo(name=name, path=path)

    def list_sessions(self) -> list[SessionInfo]:
        files = sorted(self.history_dir.glob("*.jsonl"), reverse=True)
        return [SessionInfo(name=path.stem, path=path) for path in files]

    def delete(self, name: str) -> bool:
        """Delete session ``name`` and its summary. False when it isn't there."""
        if not name or Path(name).name != name:
            return False
        path = self.history_dir / f"{name}.jsonl"
        if not path.is_file():
            return False
        path.unlink()
        summary = _summary_path_for(path)
        if summary.is_file():
            summary.unlink()
        return True

    def clear(self) -> None:
        """Forget the current session's history, keeping the session file."""
        self._messages = []
        self._summary = None
        self._summary_upto = 0
        self._rewrite()
        summary = self._summary_path()
        if summary is not None and summary.is_file():
            summary.unlink()

    def message_count(self) -> int:
        """How many messages the current session holds."""
        return len(self._messages)

    def rollback(self, size: int) -> None:
        """Drop every message added after the first ``size``, file included.

        An aborted turn (interrupted or failed) would otherwise leave a
        half-written transcript -- a dangling user message, or tool results
        whose call fell off the end.
        """
        size = max(0, size)
        if size >= len(self._messages):
            return
        self._messages = self._messages[:size]
        self._rewrite()
        if self._summary_upto > size:
            self._summary = None
            self._summary_upto = 0
            summary = self._summary_path()
            if summary is not None and summary.is_file():
                summary.unlink()

    def add_message(self, role: str, content: str, **extra: Any) -> dict[str, Any]:
        """Append a message to history and the session file.

        Extra keys (``tool_calls``, ``tool_call_id``) are stored alongside.
        """
        if self.session_path is None:
            # create() resets the message list, so it has to come first.
            self.create()
        message = {"role": role, "content": content, **extra}
        self._messages.append(message)
        assert self.session_path is not None
        with self.session_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(message, ensure_ascii=False) + "\n")
        return message

    def get_messages(self) -> list[dict[str, Any]]:
        """Assemble the request messages: system prompt plus recent history.

        History beyond RECENT_MESSAGE_LIMIT is replaced by an LLM summary.
        """
        messages = [{"role": "system", "content": self._system_prompt()}]
        history = self._messages
        if len(history) > RECENT_MESSAGE_LIMIT:
            summary = self._ensure_summary(history)
            if summary:
                messages.append(
                    {
                        "role": "system",
                        "content": f"Earlier conversation summary:\n{summary}",
                    }
                )
            history = history[-RECENT_MESSAGE_LIMIT:]
            while history and history[0]["role"] == "tool":
                # A tool result whose tool_call fell off the left edge is an
                # orphan the API rejects.
                history = history[1:]
        messages.extend(history)
        return messages

    def read_soul(self) -> str:
        """The persona text from soul.md, or the builtin default."""
        if self.soul_path.is_file():
            text = self.soul_path.read_text(encoding="utf-8").strip()
            if text:
                return text
        return BUILTIN_SOUL

    def update_soul(self, text: str) -> None:
        """Rewrite soul.md with ``text`` (no-op when blank)."""
        cleaned = text.strip()
        if not cleaned:
            return
        self.soul_path.parent.mkdir(parents=True, exist_ok=True)
        self.soul_path.write_text(cleaned + "\n", encoding="utf-8")

    def _system_prompt(self) -> str:
        return (
            "你是 Nono，一个相信基座模型力量的小助手。\n"
            "下面是你的人格设定，请始终遵循。\n\n"
            f"{self.read_soul()}\n\n"
            "你可以调用 bash 工具执行命令（查看目录、读取文件等）："
            "只读命令会直接放行，写命令会先询问用户。"
            "需要了解环境时就主动使用，不要假装执行过。\n"
            "用户若明确要求执行某个工作流，说明书会被注入上下文；"
            "不要主动去读工作流目录。\n"
            "若你认为人格需要更新（用户明确要求，或出现应长期记住的自我约束），"
            "在回复末尾输出完整的新人格全文，包在 <soul>...</soul> 中。"
            "不要把该标签展示给用户。没有必要更新时不要输出该标签。"
        )

    def _ensure_summary(self, history: list[dict[str, Any]]) -> str | None:
        """Summarize the overflow part of ``history``, caching by cutoff."""
        cutoff = len(history) - RECENT_MESSAGE_LIMIT
        if cutoff <= 0:
            return self._summary
        if self._summary is not None and cutoff <= self._summary_upto:
            return self._summary
        rendered = []
        for message in history[:cutoff]:
            role = message.get("role", "unknown")
            content = message.get("content", "")
            rendered.append(f"{role}: {content}")
        prompt = (
            "请将以下对话压缩成一段简洁摘要，保留约定、事实、未完成事项和关键结论。"
            "只输出摘要正文。\n\n" + "\n".join(rendered)
        )
        try:
            text = self._llm.chat(prompt).strip()
        except Exception:
            # A failed summary call must not break the turn. Keep whatever we
            # summarized before and try again on a later turn.
            return self._summary
        if not text:
            return self._summary
        self._summary = text
        self._summary_upto = cutoff
        self._save_summary()
        return self._summary

    def _rewrite(self) -> None:
        """Rewrite the session file so it matches the in-memory messages."""
        if self.session_path is None:
            return
        with self.session_path.open("w", encoding="utf-8") as handle:
            for message in self._messages:
                handle.write(json.dumps(message, ensure_ascii=False) + "\n")

    def _summary_path(self) -> Path | None:
        return None if self.session_path is None else _summary_path_for(self.session_path)

    def _load_summary(self) -> None:
        """Restore a persisted summary, so a long session isn't re-summarized."""
        self._summary = None
        self._summary_upto = 0
        path = self._summary_path()
        if path is None or not path.is_file():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            upto = int(data["upto"])
            text = str(data["text"]).strip()
        except (OSError, ValueError, KeyError, TypeError):
            return
        if text and upto > 0:
            self._summary = text
            self._summary_upto = upto

    def _save_summary(self) -> None:
        path = self._summary_path()
        if path is None or self._summary is None:
            return
        payload = {"upto": self._summary_upto, "text": self._summary}
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict) and "role" in item and "content" in item:
                messages.append(item)
        return messages


def _summary_path_for(session_path: Path) -> Path:
    """Sidecar holding the cached summary of one session's overflow."""
    return session_path.with_suffix(".summary.json")
