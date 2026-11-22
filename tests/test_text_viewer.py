from pycommander.text_viewer import detect_text_content, format_hex_dump


def test_find_case_insensitive_simulation():
    body = "Foo bar foo"
    assert body.lower().find("foo".lower()) == 0


def test_detect_utf8():
    text, enc = detect_text_content(b"hello", "auto")
    assert text == "hello"
    assert enc == "utf-8"


def test_hex_dump():
    out = format_hex_dump(bytes(range(32)))
    assert "00000000" in out
    assert len(out.splitlines()) >= 2