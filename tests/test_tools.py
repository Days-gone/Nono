from src.tools import TOOLS


def test_every_tool_has_a_unique_name_and_help():
    assert TOOLS
    names = [tool.name for tool in TOOLS]
    assert len(names) == len(set(names))
    for tool in TOOLS:
        assert tool.name.strip()
        assert tool.help.strip()
