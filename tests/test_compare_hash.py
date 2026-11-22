from pycommander.compare_logic import files_equal, file_hash, diff_trees


def test_files_equal(tmp_path):
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    a.write_bytes(b"same")
    b.write_bytes(b"same")
    assert files_equal(a, b)
    assert file_hash(a) == file_hash(b)


def test_diff_trees(tmp_path):
    left = tmp_path / "L"
    right = tmp_path / "R"
    left.mkdir()
    right.mkdir()
    (left / "only_l.txt").write_text("1", encoding="utf-8")
    (right / "only_r.txt").write_text("2", encoding="utf-8")
    d = diff_trees(left, right)
    assert "only_l.txt" in d["only_left"]
    assert "only_r.txt" in d["only_right"]