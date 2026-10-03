from src.apps.cli import _last_block_end


def test_blank_line_marks_block_end():
    text = "第一段。\n\n第二段还在写"
    assert text[: _last_block_end(text, 0)] == "第一段。\n"


def test_blank_inside_code_fence_is_ignored():
    text = "```python\na = 1\n\nb = 2\n```\n\n之后"
    finished = text[: _last_block_end(text, 0)]
    assert finished.endswith("```\n")


def test_no_blank_line_returns_minus_one():
    assert _last_block_end("一句话", 0) == -1
