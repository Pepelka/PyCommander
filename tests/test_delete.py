from pathlib import Path
from unittest.mock import patch

from pycommander.delete_ops import delete_paths


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