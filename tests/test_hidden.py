import pytest


@pytest.mark.win32
def test_hidden_name_filter():
    from pathlib import Path
    from pycommander.selection import is_hidden_entry

    assert is_hidden_entry(".git", Path(".git"), False) is True
    assert is_hidden_entry("normal", Path("normal"), False) is False