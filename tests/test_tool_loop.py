import json

from src.core.context import ContextManager
from src.core.llm import TurnChunk
from src.core.nono import MAX_TOOL_ROUNDS, Nono
from src.tools import BashResult


class StubLLM:
    """Plays back canned assistant turns, one list of chunks per API call."""

    def __init__(self, turns: list[list[TurnChunk]]) -> None:
        self.turns = list(turns)

    def stream_turn(self, messages, tools=None):
        for chunk in self.turns.pop(0):
            yield chunk

    def chat(self, prompt) -> str:
        return ""


def _fake_run_bash(command: str, ask=None, **kwargs) -> BashResult:
    """Emulates run_bash's contract without touching a real shell."""
    if not command.strip().startswith(("ls", "echo", "cat")):
        if ask is None or not ask(command):
            return BashResult(output="未获得执行许可。", denied=True)
    return BashResult(output="file.txt", exit_code=0)


def _nono(tmp_path, monkeypatch, llm: StubLLM) -> Nono:
    monkeypatch.setattr("src.tools.run_bash", _fake_run_bash)
    return Nono(
        llm=llm,
        context=ContextManager(llm, history_dir=tmp_path / "h", soul_path=tmp_path / "s.md"),
        workflow_dir=tmp_path / ".workflows",
    )


def _bash_call(command: str) -> dict[str, str]:
    return {"id": "call-1", "name": "bash", "arguments": json.dumps({"command": command})}


def test_model_tool_call_round_trip(tmp_path, monkeypatch):
    llm = StubLLM([
        [TurnChunk(tool_calls=[_bash_call("ls")])],
        [TurnChunk(text="目录里有 file.txt"), TurnChunk(tool_calls=[])],
    ])
    nono = _nono(tmp_path, monkeypatch, llm)
    events = list(nono.reply_stream("看看目录里有什么"))

    uses = [event.tool_use for event in events if event.tool_use]
    assert len(uses) == 1
    assert uses[0].name == "bash" and not uses[0].denied
    assert "file.txt" in "".join(event.text for event in events)
    assert events[-1].done
    roles = [m["role"] for m in nono.context.get_messages()]
    assert "tool" in roles  # the result went back into the conversation


def test_denied_write_command_is_reported_back(tmp_path, monkeypatch):
    llm = StubLLM([
        [TurnChunk(tool_calls=[_bash_call("rm -rf x")])],
        [TurnChunk(text="好吧，那我不动它。"), TurnChunk(tool_calls=[])],
    ])
    nono = _nono(tmp_path, monkeypatch, llm)
    events = list(nono.reply_stream("把这个目录删了", ask=lambda cmd: False))

    uses = [event.tool_use for event in events if event.tool_use]
    assert len(uses) == 1 and uses[0].denied
    tool_messages = [m for m in nono.context.get_messages() if m["role"] == "tool"]
    assert "拒绝" in tool_messages[0]["content"]


def test_tool_loop_stops_at_max_rounds(tmp_path, monkeypatch):
    llm = StubLLM([[TurnChunk(tool_calls=[_bash_call("ls")])] for _ in range(MAX_TOOL_ROUNDS)])
    nono = _nono(tmp_path, monkeypatch, llm)
    events = list(nono.reply_stream("一直列目录，别停"))

    assert sum(1 for event in events if event.tool_use) == MAX_TOOL_ROUNDS
    assert "上限" in "".join(event.text for event in events)
    assert events[-1].done


def test_plain_reply_without_tools_still_works(tmp_path, monkeypatch):
    llm = StubLLM([[TurnChunk(text="你好"), TurnChunk(text="呀"), TurnChunk(tool_calls=[])]])
    nono = _nono(tmp_path, monkeypatch, llm)
    reply = nono.reply("打个招呼")
    assert reply.text == "你好呀"
