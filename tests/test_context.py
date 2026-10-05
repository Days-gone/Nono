import json

from src.core.context import RECENT_MESSAGE_LIMIT, ContextManager


class StubLLM:
    """ContextManager only calls chat() for summaries."""

    def __init__(self, answer: str = "") -> None:
        self.answer = answer
        self.prompts: list[str] = []

    def chat(self, prompt) -> str:
        self.prompts.append(str(prompt))
        return self.answer


class FailingLLM:
    """Summaries blow up; the turn must survive anyway."""

    def chat(self, prompt) -> str:
        raise RuntimeError("摘要调用失败")


def _context(tmp_path, llm) -> ContextManager:
    return ContextManager(
        llm,
        history_dir=tmp_path / "history",
        soul_path=tmp_path / "soul.md",
    )


def _lines(context: ContextManager) -> list[str]:
    assert context.session_path is not None
    text = context.session_path.read_text(encoding="utf-8")
    return [line for line in text.splitlines() if line.strip()]


def test_create_avoids_reusing_a_name_within_the_same_second(tmp_path):
    context = _context(tmp_path, StubLLM())
    first = context.create()
    second = context.create()
    assert first.name != second.name
    assert first.path != second.path


def test_rollback_drops_messages_and_rewrites_the_file(tmp_path):
    context = _context(tmp_path, StubLLM())
    context.create()
    context.add_message("user", "一")
    context.add_message("assistant", "二")
    context.rollback(1)

    assert context.message_count() == 1
    lines = _lines(context)
    assert len(lines) == 1
    assert json.loads(lines[0])["content"] == "一"


def test_rollback_past_the_end_is_a_no_op(tmp_path):
    context = _context(tmp_path, StubLLM())
    context.create()
    context.add_message("user", "一")
    context.rollback(5)
    assert context.message_count() == 1


def test_clear_empties_the_session_file(tmp_path):
    context = _context(tmp_path, StubLLM())
    context.create()
    context.add_message("user", "一")
    context.clear()
    assert context.message_count() == 0
    assert _lines(context) == []


def test_delete_removes_the_session_file(tmp_path):
    context = _context(tmp_path, StubLLM())
    context.create()
    name = context.session_name
    assert context.delete(name) is True
    assert not (tmp_path / "history" / f"{name}.jsonl").exists()
    assert context.delete(name) is False


def test_delete_rejects_path_traversal(tmp_path):
    context = _context(tmp_path, StubLLM())
    context.create()
    assert context.delete("../escape") is False


def test_summary_is_persisted_and_reused_across_resume(tmp_path):
    llm = StubLLM("这是摘要")
    context = _context(tmp_path, llm)
    context.create()
    for index in range(RECENT_MESSAGE_LIMIT + 10):
        context.add_message("user", f"消息 {index}")
    context.get_messages()
    assert len(llm.prompts) == 1

    fresh = StubLLM("不该被再次调用")
    resumed = _context(tmp_path, fresh)
    resumed.resume(context.session_name)
    messages = resumed.get_messages()
    assert fresh.prompts == []
    assert any("这是摘要" in m["content"] for m in messages if m["role"] == "system")


def test_summary_failure_falls_back_to_recent_history(tmp_path):
    context = _context(tmp_path, FailingLLM())
    context.create()
    for index in range(RECENT_MESSAGE_LIMIT + 5):
        context.add_message("user", f"消息 {index}")
    messages = context.get_messages()  # must not raise
    assert len(messages) == 1 + RECENT_MESSAGE_LIMIT
