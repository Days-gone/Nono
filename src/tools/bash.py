"""The bash tool: run shell commands, auto-approving read-only ones.

Classification is deliberately conservative: the line is split on shell
operators without honoring quoting, and every segment's base command must be
whitelisted read-only. Asking too often is accepted as the safe direction.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_OUTPUT_CHARS = 10_000
DEFAULT_TIMEOUT = 60

# The tool as the model sees it (OpenAI function calling format).
BASH_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "bash",
        "description": "执行 bash 命令。只读命令直接放行；写命令会先向用户请求许可，可能被拒绝。",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的 bash 命令，例如 ls -la"},
            },
            "required": ["command"],
        },
    },
}

# Commands that only read and print, never mutating files or system state.
# Deliberately NOT here: sed/awk (sed -i, awk's ">" write files), tar,
# curl/wget (network), python/node (arbitrary code) -- they all ask.
_READONLY_COMMANDS = frozenset({
    # file viewing
    "ls", "cat", "head", "tail", "less", "more", "file", "stat", "wc", "du", "df", "tree", "diff", "comm",
    # searching
    "grep", "rg", "find", "which", "whereis", "type", "command", "man", "help",
    # text munging (stdout only)
    "echo", "printf", "sort", "uniq", "cut", "tr", "basename", "dirname", "realpath", "readlink", "base64",
    # system info
    "pwd", "cd", "date", "whoami", "hostname", "uname", "id", "env", "printenv", "uptime", "ps", "history",
    "true", "false", "test",
    # checksums / hex dumps
    "md5sum", "sha1sum", "sha256sum", "xxd", "od",
})

# git subcommands that never change the repository.
# branch/tag/remote/stash are NOT here: bare they list, with args they write.
_READONLY_GIT = frozenset({
    "status", "log", "diff", "show", "blame", "shortlog", "reflog", "grep",
    "ls-files", "ls-tree", "cat-file", "rev-parse", "rev-list", "describe",
    "name-rev", "show-branch", "count-objects", "verify-commit", "verify-tag",
})

_SPLIT_RE = re.compile(r"&&|\|\||[;|\n]")
_FD_DUP_RE = re.compile(r"\d?>&\d")  # 2>&1 and friends are not file writes
_WRITE_REDIRECT_RE = re.compile(r">")
_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# git global flags that consume the next token as their value.
_GIT_VALUE_FLAGS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}


@dataclass(frozen=True)
class BashResult:
    """Outcome of one bash call. ``denied`` means the command never ran."""

    output: str = ""
    exit_code: int | None = None
    denied: bool = False


def is_readonly(command: str) -> bool:
    """Whether every segment of the command line is whitelisted read-only."""
    line = command.strip()
    if not line or "$(" in line or "`" in line:
        # Command substitution can't be verified by this simple parser.
        return False
    if _WRITE_REDIRECT_RE.search(_FD_DUP_RE.sub("", line)):
        return False
    segments = [s.strip() for s in _SPLIT_RE.split(line) if s.strip()]
    return bool(segments) and all(_segment_is_readonly(s) for s in segments)


def _segment_is_readonly(segment: str) -> bool:
    try:
        tokens = shlex.split(segment, posix=True)
    except ValueError:
        return False
    while tokens and _ENV_ASSIGN_RE.match(tokens[0]):
        tokens = tokens[1:]
    if not tokens:
        return False
    base = tokens[0].rsplit("/", 1)[-1]
    if base == "sudo":
        return False
    if base == "git":
        return _git_is_readonly(tokens[1:])
    return base in _READONLY_COMMANDS


def _git_is_readonly(args: list[str]) -> bool:
    index = 0
    while index < len(args):
        token = args[index]
        if token in _GIT_VALUE_FLAGS:
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        return token in _READONLY_GIT
    return False


def run_bash(
    command: str,
    ask: Callable[[str], bool] | None = None,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    cwd: str | Path | None = None,
) -> BashResult:
    """Run ``command`` under bash.

    Args:
        command: The shell command line.
        ask: Permission prompt for non-read-only commands; without one they
            are denied.
        timeout: Seconds before the command is killed.
        cwd: Working directory, defaulting to the current one.

    Returns:
        A BashResult. Ordinary failures (bash missing, timeout, nonzero
        exit) come back in the result rather than raising.
    """
    command = command.strip()
    if not command:
        return BashResult(output="空命令。")
    if not is_readonly(command):
        if ask is None or not ask(command):
            return BashResult(output="未获得执行许可。", denied=True)
    try:
        completed = subprocess.run(
            ["bash", "-c", command],
            capture_output=True,
            stdin=subprocess.DEVNULL,  # an interactive stdin would hang the caller
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=cwd,
        )
    except FileNotFoundError:
        return BashResult(output="未找到 bash：请确认它在 PATH 上（Windows 下可用 Git Bash）。")
    except subprocess.TimeoutExpired:
        return BashResult(output=f"执行超时（{timeout:g} 秒），已终止。")
    output = completed.stdout or ""
    if completed.stderr:
        output += ("\n" if output else "") + completed.stderr
    if len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS] + "\n……（输出过长，已截断）"
    return BashResult(output=output, exit_code=completed.returncode)
