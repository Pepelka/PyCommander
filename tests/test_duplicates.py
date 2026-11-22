from pycommander.duplicates import find_duplicates


def test_find_dupes(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    data = b"duplicate content"
    a.write_bytes(data)
    b.write_bytes(data)
    groups = find_duplicates(tmp_path)
    assert len(groups) >= 1