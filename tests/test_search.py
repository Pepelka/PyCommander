from pycommander.search import search_files


def test_search_name(tmp_path):
    (tmp_path / "needle.txt").write_text("body", encoding="utf-8")
    (tmp_path / "other.txt").write_text("x", encoding="utf-8")
    hits = search_files(tmp_path, name_contains="needle")
    assert len(hits) == 1