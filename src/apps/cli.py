"""Nono's terminal app: REPL, slash commands, streaming Markdown, desk pet."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.prompt import Confirm
from rich.table import Table
from rich.text import Text

from src.apps.pet import NonoPet, REFRESH_INTERVAL
from src.core.context import SessionInfo
from src.core.nono import Nono, ToolUse

console = Console()

_HISTORY_FILE = Path.home() / ".nono_history"
_PROMPT_TEXT = "Nono > "
_PROMPT_MARKUP = f"[bold cyan]{_PROMPT_TEXT}[/bold cyan]"
_PROMPT_HTML = HTML("<b><ansicyan>Nono &gt; </ansicyan></b>")


@dataclass(frozen=True)
class _Command:
    name: str
    help: str


# Single source of truth for both the completion menu and what the REPL accepts.
_COMMANDS: tuple[_Command, ...] = (
    _Command("/exit", "退出 Nono"),
    _Command("/new", "新建一个会话"),
    _Command("/clear", "清空当前会话的历史"),
    _Command("/resume", "切换、新建或删除会话"),
    _Command("/workflow", "列出或加载 .workflows/ 中的工作流"),
    _Command("/tools", "列出可用的工具"),
    _Command("/bash", "执行 bash 命令（写命令会先询问）"),
)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        nono = Nono()
        session = nono.start()
    except AssertionError as error:
        console.print(f"[red]配置错误：{error}[/red]")
        console.print("请在项目根目录复制 [bold].env.example[/bold] 为 [bold].env[/bold] 并填入配置。")
        return 1
    except OSError as error:
        console.print(f"[red]启动失败：{error}[/red]")
        return 1

    # Markdown only makes sense on a terminal; piped output stays verbatim.
    markdown = args.markdown and console.is_terminal

    # The pet tracks moods even when hidden: observe/cheer/sulk stay cheap
    # no-ops, and --no-pet only stops the drawing.
    pet = None if args.no_pet else NonoPet()
    prompt_session = _prompt_session(pet, nono.list_workflows)

    if console.is_terminal:
        if pet is not None and prompt_session is None:
            # This terminal can't run prompt_toolkit (e.g. Git Bash): greet
            # with one static frame so the pet is at least present.
            _print_pet(pet)
        console.print("[bold]Nono[/bold] 已启动。输入 [yellow]/tools[/yellow] 查看工具，[yellow]/workflow[/yellow] 加载工作流，[yellow]/resume[/yellow] 切换会话，[yellow]/exit[/yellow] 退出。")
        console.print(f"[dim]当前会话：{session.name}[/dim]")
    else:
        console.print(f"Nono 已启动。当前会话：{session.name}。")

    while True:
        try:
            raw = _read_line(prompt_session)
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]再见。[/dim]")
            return 0

        if pet is not None:
            pet.observe()
        line = raw.strip()
        if not line:
            continue
        if line == "/exit":
            console.print("[dim]再见。[/dim]")
            return 0
        if line == "/new":
            session = nono.create_session()
            console.print(f"[dim]已新建会话：{session.name}[/dim]")
            continue
        if line == "/clear":
            if Confirm.ask("清空当前会话历史？此操作不可撤销", default=False):
                nono.clear_session()
                console.print("[dim]已清空当前会话历史。[/dim]")
            else:
                console.print("[dim]已取消。[/dim]")
            continue
        if line == "/resume":
            _resume(nono)
            continue
        if line == "/workflow" or line.startswith("/workflow "):
            _workflow(nono, line[len("/workflow"):].strip())
            continue
        if line == "/tools":
            _tools(nono)
            continue
        if line == "/bash" or line.startswith("/bash "):
            _bash(nono, line[len("/bash"):].strip())
            continue

        printer = _ReplyPrinter(console, markdown=markdown)
        stream = nono.reply_stream(line, ask=lambda cmd: _ask_while_streaming(printer, cmd))
        try:
            try:
                for event in stream:
                    if event.tool_use is not None:
                        _print_tool_use(event.tool_use)
                    if event.text:
                        printer.feed(event.text)
                    if event.done:
                        printer.close()
                if pet is not None:
                    pet.cheer()
            finally:
                # Closing explicitly (rather than waiting for GC) is what makes
                # the rollback of an interrupted turn deterministic.
                stream.close()
                printer.close()
        except KeyboardInterrupt:
            console.print("[dim]已中断本次回复（本轮未写入历史）。[/dim]")
            continue
        except Exception as error:
            if pet is not None:
                pet.sulk()
            console.print(f"[red]调用失败：{error}[/red]")
            continue
    return 0


class _SlashCompleter(Completer):
    """Offers slash commands, and workflow names after ``/workflow ``."""

    def __init__(self, workflow_names: Callable[[], list[str]] | None = None) -> None:
        self._workflow_names = workflow_names

    def get_completions(self, document, complete_event):
        typed = document.text_before_cursor
        if not typed.startswith("/"):
            return
        head, space, partial = typed.partition(" ")
        if not space:
            for command in _COMMANDS:
                if command.name.startswith(typed):
                    yield Completion(
                        command.name,
                        start_position=-len(typed),
                        display_meta=command.help,
                    )
            return
        if head == "/workflow" and self._workflow_names is not None and " " not in partial:
            for name in self._workflow_names():
                if name.startswith(partial):
                    yield Completion(
                        name,
                        start_position=-len(partial),
                        display_meta="工作流",
                    )


def _prompt_session(
    pet: NonoPet | None,
    workflow_names: Callable[[], list[str]] | None = None,
) -> PromptSession | None:
    """Build the PromptSession, or None when prompt_toolkit can't drive this terminal.

    Piped IO and Git Bash/mintty on Windows (not a Win32 console) fall back
    to a plain ``console.input`` prompt. With a full terminal the pet rides
    along as the multiline prompt message, kept animated by the session's
    ``refresh_interval``.
    """
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return None
    if sys.platform == "win32" and not _has_win32_console():
        console.print(
            "[dim]此终端不支持命令补全和桌宠（Git Bash / mintty 不是 Windows 控制台）；"
            "在 Windows Terminal 或 cmd 中运行可看到完整界面。[/dim]"
        )
        return None
    message = _PROMPT_HTML if pet is None else pet.render
    return PromptSession(
        message=message,
        completer=_SlashCompleter(workflow_names),
        complete_while_typing=True,
        reserve_space_for_menu=len(_COMMANDS),
        history=FileHistory(str(_HISTORY_FILE)),
        refresh_interval=REFRESH_INTERVAL if pet is not None else 0,
    )


def _has_win32_console() -> bool:
    """Whether prompt_toolkit can render here, i.e. stdout is a Win32 console."""
    from prompt_toolkit.output import create_output
    from prompt_toolkit.output.win32 import NoConsoleScreenBufferError

    try:
        create_output()
    except NoConsoleScreenBufferError:
        return False
    return True


def _read_line(prompt_session: PromptSession | None) -> str:
    if prompt_session is None:
        return console.input(_PROMPT_MARKUP)
    return prompt_session.prompt()


# prompt_toolkit ANSI style names used by the pet, translated for rich.
_PT_TO_RICH_STYLE = {
    "ansibrightcyan bold": "bold bright_cyan",
    "ansiwhite bold": "bold white",
    "ansibrightblack": "bright_black",
    "ansicyan bold": "bold cyan",
}


def _print_pet(pet: NonoPet) -> None:
    """Print one static pet frame with rich -- for the startup banner."""
    text = Text()
    for style, chunk in pet.block():
        text.append(chunk, style=_PT_TO_RICH_STYLE.get(style, ""))
    console.print(text)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="nono", description="Nono 命令行")
    parser.add_argument(
        "--no-markdown",
        dest="markdown",
        action="store_false",
        help="把回复当作纯文本流式输出，不做 Markdown 渲染",
    )
    parser.add_argument(
        "--no-pet",
        action="store_true",
        help="不在输入行上方显示桌宠",
    )
    return parser.parse_args(argv)


class _ReplyPrinter:
    """Streams an assistant reply to the console, optionally as Markdown.

    Finished blocks are printed for good as they end, so the ``Live`` region
    only ever holds the block still being written; a live region taller than
    the terminal cannot be repainted reliably.
    """

    def __init__(self, console: Console, markdown: bool = True) -> None:
        self._console = console
        self._markdown = markdown
        self._text = ""
        self._flushed = 0
        self._live: Live | None = None
        self._closed = False

    def feed(self, chunk: str) -> None:
        if self._closed or not chunk:
            return
        if not self._markdown:
            self._console.print(chunk, end="", markup=False, highlight=False, soft_wrap=True)
            return
        self._text += chunk
        self._flush()
        self._refresh()

    def pause(self) -> None:
        """Freeze the reply so a prompt can take over the terminal.

        On-screen text stays as printed so far; the next ``feed`` opens a
        fresh live region below the prompt instead of fighting it.
        """
        if self._closed:
            return
        if self._live is not None:
            self._live.stop()
            self._live = None
        self._flushed = len(self._text)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if not self._markdown:
            self._console.print()
            return
        if self._live is not None:
            # Live.stop() leaves the last render on screen, so the tail printed
            # by the live region is what the user keeps.
            self._live.stop()
            return
        self._print(self._text[self._flushed :])

    def _flush(self) -> None:
        split = _last_block_end(self._text, self._flushed)
        if split <= self._flushed:
            return
        self._print(self._text[self._flushed : split])
        self._flushed = split

    def _refresh(self) -> None:
        tail = self._text[self._flushed :]
        if not tail.strip():
            # The last flush swallowed the tail; clear whatever it left behind.
            if self._live is not None:
                self._live.update(Markdown(""))
            return
        if self._live is None:
            self._live = Live(
                Markdown(tail),
                console=self._console,
                refresh_per_second=8,
                vertical_overflow="visible",
            )
            self._live.start(refresh=True)
        else:
            self._live.update(Markdown(tail))

    def _print(self, text: str) -> None:
        if text.strip():
            self._console.print(Markdown(text))


def _last_block_end(text: str, start: int) -> int:
    """Offset of the last blank line outside a code fence, or -1 if there is none.

    Everything before it is a finished Markdown block that can be rendered on
    its own without changing how it looks.
    """
    fenced = False
    blank_before = True
    end = -1
    offset = start
    for line in text[start:].splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            fenced = not fenced
            blank_before = False
        elif not fenced and not stripped:
            if not blank_before:
                end = offset
            blank_before = True
        else:
            blank_before = False
        offset += len(line)
    return end


def _bash(nono: Nono, command: str) -> None:
    if not command:
        console.print("[dim]用法：/bash <命令>[/dim]")
        return
    result = nono.run_bash(command, ask=_confirm_bash)
    if result.denied:
        console.print("[dim]已取消执行。[/dim]")
        return
    if result.exit_code is None:
        # Never ran: bash missing, timed out, or empty command.
        console.print(f"[red]{result.output}[/red]")
        return
    if result.output:
        # Command output is data, not markup: print it verbatim.
        console.print(result.output, markup=False, highlight=False, soft_wrap=True)
    else:
        console.print("[dim]（无输出）[/dim]")
    if result.exit_code != 0:
        console.print(f"[red]退出码：{result.exit_code}[/red]")


def _confirm_bash(command: str) -> bool:
    return Confirm.ask(f"执行写命令 [bold cyan]{command}[/bold cyan] ？", default=False)


def _ask_while_streaming(printer: _ReplyPrinter, command: str) -> bool:
    """Permission prompt mid-reply: free the terminal before asking."""
    printer.pause()
    return _confirm_bash(command)


def _print_tool_use(use: ToolUse) -> None:
    console.print(f"[dim]⚙ 调用工具 {use.name}: {use.arguments}[/dim]")
    if use.output:
        lines = use.output.splitlines()
        preview = "\n".join(lines[:6])
        if len(lines) > 6:
            preview += "\n……"
        # Tool output is data, not markup: print it verbatim.
        console.print(preview, style="dim", markup=False, highlight=False, soft_wrap=True)


def _tools(nono: Nono) -> None:
    table = Table(title="工具列表", show_lines=False)
    table.add_column("名称", style="white")
    table.add_column("可用方式", style="cyan")
    table.add_column("说明", style="dim")
    for tool in nono.list_tools():
        how = "模型可调用" if tool.model_callable else "仅斜杠命令"
        table.add_row(tool.name, how, tool.help)
    console.print(table)
    console.print("[dim]模型只能主动调用「模型可调用」的工具；其余工具由你用斜杠命令触发。[/dim]")


def _workflow(nono: Nono, name: str) -> None:
    """``/workflow`` lists, ``/workflow <名称>`` loads into the session."""
    if not name:
        workflows = nono.list_workflows()
        if not workflows:
            console.print("[dim]当前目录没有可用工作流（.workflows/<名称>/ 目录）。[/dim]")
            return
        table = Table(title="工作流列表", show_lines=False)
        table.add_column("名称", style="white")
        for workflow in workflows:
            table.add_row(workflow)
        console.print(table)
        return

    loaded = nono.load_workflow(name)
    if loaded is None:
        console.print(f"[red]未找到工作流：{name}[/red][dim]（应为 .workflows/{name}/ 目录，内含 md 文件）[/dim]")
        return
    console.print(f"[yellow]已加载工作流：{loaded}[/yellow]")


def _resume(nono: Nono) -> None:
    sessions = nono.list_sessions()
    table = Table(title="会话列表", show_lines=False)
    table.add_column("序号", justify="right", style="cyan")
    table.add_column("会话", style="white")
    table.add_row("0", "新会话")
    for index, session in enumerate(sessions, start=1):
        mark = "（当前）" if session.name == nono.context.session_name else ""
        table.add_row(str(index), f"{session.name}{mark}")
    console.print(table)
    console.print("[dim]输入序号切换，输入 d<序号> 删除，输入 0 新建。[/dim]")

    choice = console.input("[bold cyan]选择序号 > [/bold cyan]").strip()
    if choice == "0":
        session = nono.create_session()
        console.print(f"[dim]已新建会话：{session.name}[/dim]")
        return

    if choice[:1] in ("d", "D"):
        _delete_session(nono, sessions, choice[1:].strip())
        return

    if not choice.isdigit():
        console.print("[red]无效序号，仍留在当前会话。[/red]")
        return

    index = int(choice)
    if index < 1 or index > len(sessions):
        console.print("[red]无效序号，仍留在当前会话。[/red]")
        return

    session = nono.resume_session(sessions[index - 1].name)
    console.print(f"[dim]已切换到会话：{session.name}[/dim]")


def _delete_session(nono: Nono, sessions: list[SessionInfo], raw_index: str) -> None:
    """Handle ``d<序号>`` from the resume prompt."""
    if not raw_index.isdigit():
        console.print("[red]删除用法：d<序号>，例如 d2。[/red]")
        return
    index = int(raw_index)
    if index < 1 or index > len(sessions):
        console.print("[red]无效序号。[/red]")
        return
    target = sessions[index - 1]
    if target.name == nono.context.session_name:
        console.print("[red]不能删除当前会话，请先切换到其他会话。[/red]")
        return
    if not Confirm.ask(f"删除会话 {target.name}？此操作不可撤销", default=False):
        console.print("[dim]已取消。[/dim]")
        return
    if nono.delete_session(target.name):
        console.print(f"[dim]已删除会话：{target.name}[/dim]")
    else:
        console.print("[red]删除失败，文件可能已不存在。[/red]")


if __name__ == "__main__":
    raise SystemExit(main())
