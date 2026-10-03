from src.core.context import ContextManager
from src.tools import update_soul


class StubLLM:
    """Stands in for LLM: one canned answer, records the prompts it got."""

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.prompts: list[str] = []

    def chat(self, prompt) -> str:
        self.prompts.append(str(prompt))
        return self.answer


def _context(tmp_path) -> ContextManager:
    return ContextManager(
        StubLLM(""),
        history_dir=tmp_path / "history",
        soul_path=tmp_path / "soul.md",
    )


def test_keep_leaves_soul_untouched(tmp_path):
    context = _context(tmp_path)
    assert update_soul("今天天气不错", StubLLM("KEEP"), context) is False
    assert not (tmp_path / "soul.md").exists()


def test_new_persona_rewrites_soul(tmp_path):
    context = _context(tmp_path)
    llm = StubLLM("<soul>新人格：永远先给结论。</soul>")
    assert update_soul("以后回答都先给结论", llm, context) is True
    soul = (tmp_path / "soul.md").read_text(encoding="utf-8").strip()
    assert soul == "新人格：永远先给结论。"


def test_empty_content_never_calls_llm(tmp_path):
    context = _context(tmp_path)
    llm = StubLLM("<soul>x</soul>")
    assert update_soul("   ", llm, context) is False
    assert llm.prompts == []
