from pathlib import Path
from unittest.mock import patch

from pycommander.delete_ops import delete_paths, delete_one_path


def test_permanent_delete(tmp_path):
    f = tmp_path / "gone.txt"
    f.write_text("x", encoding="utf-8")
    errs = delete_paths([f], permanent=True)
    assert not errs
    assert not f.exists()


@patch("pycommander.delete_ops.send2trash")
def test_recycle_delete(mock_st, tmp_path):
    f = tmp_path / "rb.txt"
    f.write_text("x", encoding="utf-8")
    delete_paths([f], permanent=False)
    mock_st.send2trash.assert_called_once()


def test_delete_stops_on_cancel(tmp_path):
    keep = tmp_path / "keep.txt"
    drop = tmp_path / "drop.txt"
    keep.write_text("1", encoding="utf-8")
    drop.write_text("2", encoding="utf-8")
    n = {"i": 0}

    def cancel():
        n["i"] += 1
        return n["i"] > 1

    errs = delete_paths([keep, drop], permanent=True, should_cancel=cancel)
    assert not keep.exists()
    assert drop.exists()
    assert not errs


def test_delete_one_path(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("a", encoding="utf-8")
    assert delete_one_path(f, permanent=True) is None
    assert not f.exists()