"""Nono core: the reply loop with tool execution, and the streaming soul filter."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from src import tools
from src.core.context import ContextManager, SessionInfo
from src.core.llm import LLM

SOUL_OPEN = "<soul>"
SOUL_CLOSE = "</soul>"

MAX_TOOL_ROUNDS = 8

# The tools the model may call, in OpenAI function calling format.
_TOOL_SCHEMAS = [tools.BASH_SCHEMA]


@dataclass(frozen=True)
class ToolUse:
    """One tool call the model asked for and Nono executed."""

    name: str
    arguments: str
    output: str
    denied: bool = False


@dataclass(frozen=True)
class NonoReply:
    """A whole reply: ``reply_stream`` collected into one object."""

    text: str
    soul_updated: bool = False


@dataclass(frozen=True)
class NonoEvent:
    """One step of a streamed reply.

    Attributes:
        text: Incremental visible text; concatenating it gives the whole reply.
        soul_updated: Set on the final event when soul.md was rewritten.
        done: Marks the final event of the stream.
        tool_use: A tool call report between text rounds, if any.
    """

    text: str = ""
    soul_updated: bool = False
    done: bool = False
    tool_use: ToolUse | None = None


class SoulFilter:
    """Strips ``<soul>...</soul>`` from a reply while it is still streaming.

    The tag may split across chunks, so text that could still complete into
    one is held back until unambiguous -- at most a tag's length.
    """

    def __init__(self) -> None:
        self._pending = ""
        self._soul_raw = ""
        self._in_soul = False
        self._soul: str | None = None

    def feed(self, chunk: str) -> str:
        self._pending += chunk
        visible: list[str] = []
        while self._pending:
            if self._in_soul:
                index = self._pending.find(SOUL_CLOSE)
                if index < 0:
                    keep = _partial_tag_len(self._pending, SOUL_CLOSE)
                    self._soul_raw += self._pending[: len(self._pending) - keep]
                    self._pending = self._pending[len(self._pending) - keep :]
                    break
                self._soul_raw += self._pending[:index]
                self._pending = self._pending[index + len(SOUL_CLOSE) :]
                self._in_soul = False
                # Only the first soul block counts.
                if self._soul is None:
                    self._soul = self._soul_raw.strip() or None
                self._soul_raw = ""
                continue

            index = self._pending.find(SOUL_OPEN)
            if index < 0:
                keep = _partial_tag_len(self._pending, SOUL_OPEN)
                visible.append(self._pending[: len(self._pending) - keep])
                self._pending = self._pending[len(self._pending) - keep :]
                break
            visible.append(self._pending[:index])
            self._pending = self._pending[index + len(SOUL_OPEN) :]
            self._in_soul = True
        return "".join(visible)

    def finalize(self) -> tuple[str, str | None]:
        """Flush the filter.

        Returns:
            (remaining visible text, soul update if one completed). An
            unclosed tag is given back as ordinary text.
        """
        tail = self._pending
        self._pending = ""
        if self._in_soul:
            tail = SOUL_OPEN + self._soul_raw + tail
            self._soul_raw = ""
            self._in_soul = False
            self._soul = None
        return tail, self._soul


def _partial_tag_len(text: str, tag: str) -> int:
    """Length of the longest tail of ``text`` that may still complete into ``tag``."""
    for size in range(min(len(text), len(tag) - 1), 0, -1):
        if text.endswith(tag[:size]):
            return size
    return 0


class Nono:
    """Turns user text into a reply, running the model's tool-call loop.

    Model-requested tools are executed (write commands need the app's ``ask``
    approval) and their results fed back until the final text arrives. Tools
    are also exposed as methods for apps to call directly (e.g. the CLI's
    slash commands).
    """

    def __init__(
        self,
        llm: LLM | None = None,
        context: ContextManager | None = None,
        workflow_dir: Path | None = None,
    ) -> None:
        self.llm = llm or LLM()
        self.context = context or ContextManager(self.llm)
        # Like .history/, workflows live next to wherever the user runs Nono.
        self.workflow_dir = workflow_dir or (Path.cwd() / ".workflows")

    def start(self) -> SessionInfo:
        return self.context.start()

    def create_session(self) -> SessionInfo:
        return self.context.create()

    def resume_session(self, name: str) -> SessionInfo:
        return self.context.resume(name)

    def list_sessions(self) -> list[SessionInfo]:
        return self.context.list_sessions()

    def list_tools(self) -> tuple[tools.ToolInfo, ...]:
        """The tools wired into Nono, as shown by the CLI's /tools command."""
        return tools.TOOLS

    def update_soul(self, content: str) -> bool:
        """Run the update_soul tool; True when soul.md was rewritten."""
        return tools.update_soul(content, self.llm, self.context)

    def run_bash(
        self,
        command: str,
        ask: Callable[[str], bool] | None = None,
    ) -> tools.BashResult:
        """Run the bash tool; ``ask`` is the permission prompt for write commands."""
        return tools.run_bash(command, ask)

    def list_workflows(self) -> list[str]:
        """Names of the workflows available under ``workflow_dir``."""
        return tools.list_workflows(self.workflow_dir)

    def load_workflow(self, name: str) -> str | None:
        """Load workflow ``name`` into the session; None when not found."""
        return tools.load_workflow(name, self.workflow_dir, self.context)

    def reply(
        self,
        user_text: str,
        ask: Callable[[str], bool] | None = None,
    ) -> NonoReply:
        """Collect ``reply_stream`` into a single reply."""
        parts: list[str] = []
        soul_updated = False
        for event in self.reply_stream(user_text, ask):
            if event.text:
                parts.append(event.text)
            soul_updated = soul_updated or event.soul_updated
        return NonoReply(text="".join(parts).strip(), soul_updated=soul_updated)

    def reply_stream(
        self,
        user_text: str,
        ask: Callable[[str], bool] | None = None,
    ) -> Iterator[NonoEvent]:
        """Stream the reply to one user message, tool calls included.

        Args:
            user_text: What the user typed.
            ask: Permission prompt for write commands; without it they are denied.

        Yields:
            NonoEvent text pieces, tool_use reports between rounds, and one
            final ``done`` event.
        """
        text = user_text.strip()
        if not text:
            yield NonoEvent(done=True)
            return

        self.context.add_message("user", text)
        soul_updated = False
        for _round in range(MAX_TOOL_ROUNDS):
            soul_filter = SoulFilter()
            parts: list[str] = []
            tool_calls: list[dict[str, str]] = []
            for chunk in self.llm.stream_turn(self.context.get_messages(), tools=_TOOL_SCHEMAS):
                if chunk.text:
                    visible = soul_filter.feed(chunk.text)
                    if visible:
                        parts.append(visible)
                        yield NonoEvent(text=visible)
                if chunk.tool_calls is not None:
                    tool_calls = chunk.tool_calls
            tail, soul = soul_filter.finalize()
            if tail:
                parts.append(tail)
                yield NonoEvent(text=tail)
            if soul and not soul_updated:
                self.context.update_soul(soul)
                soul_updated = True
            visible_text = "".join(parts).strip()

            if not tool_calls:
                self.context.add_message("assistant", visible_text)
                break

            self.context.add_message(
                "assistant",
                visible_text,
                tool_calls=[
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {"name": call["name"], "arguments": call["arguments"]},
                    }
                    for call in tool_calls
                ],
            )
            for call in tool_calls:
                output, denied = self._run_tool(call, ask)
                yield NonoEvent(
                    tool_use=ToolUse(
                        name=call["name"],
                        arguments=call["arguments"],
                        output=output,
                        denied=denied,
                    )
                )
                self.context.add_message("tool", output, tool_call_id=call["id"])
        else:
            # The loop never broke: every round asked for more tools.
            yield NonoEvent(text=f"\n（工具调用已达 {MAX_TOOL_ROUNDS} 轮上限，先到这里。）")
        yield NonoEvent(soul_updated=soul_updated, done=True)

    def _run_tool(
        self,
        tool_call: dict[str, str],
        ask: Callable[[str], bool] | None,
    ) -> tuple[str, bool]:
        """Execute one model-requested tool call.

        Returns:
            (output, denied): the text fed back to the model, and whether
            the user refused the command.
        """
        if tool_call["name"] != "bash":
            return f"未知工具：{tool_call['name']}", False
        try:
            args = json.loads(tool_call["arguments"] or "{}")
        except json.JSONDecodeError:
            return "工具参数不是合法的 JSON。", False
        result = tools.run_bash(str(args.get("command", "")), ask)
        if result.denied:
            return "用户拒绝了该命令，没有执行。", True
        output = result.output.strip()
        if result.exit_code:
            output += f"\n（退出码：{result.exit_code}）"
        return output or "（无输出）", False
