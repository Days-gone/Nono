from src.tools import TOOLS


def test_every_tool_has_a_unique_name_and_help():
    assert TOOLS
    names = [tool.name for tool in TOOLS]
    assert len(names) == len(set(names))
    for tool in TOOLS:
        assert tool.name.strip()
        assert tool.help.strip()


def test_only_bash_is_exposed_to_the_model():
    callable_names = [tool.name for tool in TOOLS if tool.model_callable]
    assert callable_names == ["bash"]
