from pathlib import Path

from pycommander.selection import resolve_selection_paths, filter_entries


def test_resolve_marks_first(tmp_path):
    paths = resolve_selection_paths(
        tmp_path,
        {"a", "b"},
        ["c"],
        ["a", "b", "c"],
        "c",
        prefer_marks=True,
    )
    assert [p.name for p in paths] == ["a", "b"]


def test_filter_entries():
    data = [{"name": "foo.txt", "ext": "txt"}, {"name": "bar.log", "ext": "log"}]
    assert len(filter_entries(data, "foo")) == 1