from src.core.context import ContextManager
from src.tools import list_workflows, load_workflow


class StubLLM:
    """ContextManager only calls chat() for summaries, which tests never reach."""

    def chat(self, prompt) -> str:
        return ""


def _context(tmp_path) -> ContextManager:
    return ContextManager(
        StubLLM(),
        history_dir=tmp_path / "history",
        soul_path=tmp_path / "soul.md",
    )


def _make_workflow(tmp_path, name: str, files: dict[str, str]):
    directory = tmp_path / ".workflows" / name
    directory.mkdir(parents=True)
    for filename, body in files.items():
        (directory / filename).write_text(body, encoding="utf-8")
    return directory


def _loaded_messages(context: ContextManager) -> list[str]:
    return [
        message["content"]
        for message in context.get_messages()
        if message["role"] == "system" and "已加载工作流" in message["content"]
    ]


def test_load_injects_md_files_in_filename_order(tmp_path):
    _make_workflow(tmp_path, "review", {
        "02-act.md": "第二步：执行",
        "01-plan.md": "第一步：计划",
    })
    context = _context(tmp_path)
    assert load_workflow("review", tmp_path / ".workflows", context) == "review"
    messages = _loaded_messages(context)
    assert len(messages) == 1
    body = messages[0]
    assert "01-plan.md" in body and "02-act.md" in body
    assert body.index("第一步：计划") < body.index("第二步：执行")


def test_missing_workflow_loads_nothing(tmp_path):
    context = _context(tmp_path)
    assert load_workflow("nope", tmp_path / ".workflows", context) is None
    assert _loaded_messages(context) == []


def test_workflow_without_md_files_loads_nothing(tmp_path):
    _make_workflow(tmp_path, "empty", {"notes.txt": "不是 md"})
    context = _context(tmp_path)
    assert load_workflow("empty", tmp_path / ".workflows", context) is None
    assert _loaded_messages(context) == []


def test_path_traversal_is_rejected(tmp_path):
    _make_workflow(tmp_path, "review", {"a.md": "内容"})
    context = _context(tmp_path)
    assert load_workflow("../.workflows/review", tmp_path / ".workflows", context) is None
    assert _loaded_messages(context) == []


def test_list_workflows_returns_subdirectory_names(tmp_path):
    _make_workflow(tmp_path, "b", {"x.md": "x"})
    _make_workflow(tmp_path, "a", {"x.md": "x"})
    (tmp_path / ".workflows" / "stray.md").write_text("不是目录", encoding="utf-8")
    assert list_workflows(tmp_path / ".workflows") == ["a", "b"]


def test_list_workflows_without_dir(tmp_path):
    assert list_workflows(tmp_path / ".workflows") == []
