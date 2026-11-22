from pycommander.selection import filter_entries


def test_filter_case_insensitive():
    rows = [{"name": "Hello.TXT", "ext": "TXT"}]
    assert filter_entries(rows, "hello")