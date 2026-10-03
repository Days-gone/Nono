"""The workflow tool: a workflow is a directory of md files under .workflows/."""

from __future__ import annotations

from pathlib import Path

from src.core.context import ContextManager


def list_workflows(workflows_dir: Path) -> list[str]:
    """Names of available workflows: the subdirectories of ``workflows_dir``."""
    if not workflows_dir.is_dir():
        return []
    return sorted(path.name for path in workflows_dir.iterdir() if path.is_dir())


def load_workflow(name: str, workflows_dir: Path, context: ContextManager) -> str | None:
    """Inject workflow ``name`` into the session as a system message.

    A workflow is a directory inside ``workflows_dir`` whose ``*.md`` files,
    read in filename order, together make up the workflow.

    Args:
        name: Workflow directory name; anything path-like is rejected.
        workflows_dir: The ``.workflows`` root.
        context: The session receiving the system message.

    Returns:
        The workflow name when loaded, None when there was nothing to load.
    """
    name = name.strip()
    if not name or Path(name).name != name:
        # Rejects empty names and path traversal like "../other".
        return None
    workflow_dir = workflows_dir / name
    if not workflow_dir.is_dir():
        return None
    sections: list[str] = []
    for path in sorted(workflow_dir.glob("*.md")):
        body = path.read_text(encoding="utf-8").strip()
        if body:
            sections.append(f"### {path.name}\n{body}")
    if not sections:
        return None
    context.add_message(
        "system",
        f"已加载工作流 {name}：\n\n" + "\n\n".join(sections),
    )
    return name
