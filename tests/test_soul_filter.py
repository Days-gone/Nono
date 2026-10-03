from src.core.nono import SoulFilter


def run(chunks: list[str]) -> tuple[str, str | None]:
    soul_filter = SoulFilter()
    visible = "".join(soul_filter.feed(chunk) for chunk in chunks)
    tail, soul = soul_filter.finalize()
    return visible + tail, soul


def test_plain_text_passes_through():
    assert run(["你好", "，世界"]) == ("你好，世界", None)


def test_tag_split_across_chunks():
    assert run(["回复", "<so", "ul>新人格</s", "oul>"]) == ("回复", "新人格")


def test_unclosed_tag_is_treated_as_text():
    assert run(["看<soul>这其实不是标签"]) == ("看<soul>这其实不是标签", None)


def test_first_tag_wins_like_the_old_regex():
    assert run(["a<soul>一</soul>b<soul>二</soul>c"]) == ("abc", "一")
