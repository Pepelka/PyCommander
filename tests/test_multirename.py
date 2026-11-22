from pycommander.multirename import expand_rename, preview_renames


def test_expand_pattern():
    assert expand_rename("file.txt", "{stem}_{n:03d}", 5) == "file_005"


def test_preview():
    assert preview_renames(["a.txt", "b.txt"], "{n}-{name}") == [
        ("a.txt", "1-a.txt"),
        ("b.txt", "2-b.txt"),
    ]