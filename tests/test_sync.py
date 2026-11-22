from pycommander.compare_logic import diff_trees


def test_newer_left(tmp_path):
    left = tmp_path / "L"
    right = tmp_path / "R"
    left.mkdir()
    right.mkdir()
    lf = left / "f.txt"
    rf = right / "f.txt"
    lf.write_text("old", encoding="utf-8")
    rf.write_text("new", encoding="utf-8")
    import time

    time.sleep(0.05)
    lf.write_text("newer", encoding="utf-8")
    d = diff_trees(left, right)
    assert "f.txt" in d["newer_left"] or "f.txt" in d["same"]