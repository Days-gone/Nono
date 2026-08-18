from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from rich.console import Console
from rich.table import Table

from src.core.nono import Nono

console = Console()


def main() -> int:
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

    console.print("[bold]Nono[/bold] 已启动。输入 [yellow]/resume[/yellow] 切换会话，[yellow]/exit[/yellow] 退出。")
    console.print(f"[dim]当前会话：{session.name}[/dim]")

    while True:
        try:
            raw = console.input("[bold cyan]Nono › [/bold cyan]")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]再见。[/dim]")
            return 0

        line = raw.strip()
        if not line:
            continue
        if line == "/exit":
            console.print("[dim]再见。[/dim]")
            return 0
        if line == "/resume":
            _resume(nono)
            continue

        try:
            result = nono.reply(line)
        except Exception as error:
            console.print(f"[red]调用失败：{error}[/red]")
            continue

        if result.workflow_name:
            console.print(f"[yellow]已加载工作流：{result.workflow_name}[/yellow]")
        if result.soul_updated:
            console.print("[yellow]已更新人格文件 configs/soul.md[/yellow]")
        if result.text:
            console.print(f"[green]{result.text}[/green]")
    return 0


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

    choice = console.input("[bold cyan]选择序号 › [/bold cyan]").strip()
    if choice == "0":
        session = nono.create_session()
        console.print(f"[dim]已新建会话：{session.name}[/dim]")
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


if __name__ == "__main__":
    raise SystemExit(main())
