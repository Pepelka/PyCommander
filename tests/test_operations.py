from pathlib import Path
from unittest.mock import MagicMock

from pycommander.conflict import ConflictResolver
from pycommander.operations import copy_file_with_conflict, move_with_conflict


def test_copy_file_new(tmp_path):
    src = tmp_path / "a.txt"
    src.write_text("hello", encoding="utf-8")
    dst_dir = tmp_path / "dest"
    dst_dir.mkdir()
    resolver = ConflictResolver(MagicMock())
    resolver.overwrite_all = True
    assert copy_file_with_conflict(src, dst_dir, resolver) == "copied"
    assert (dst_dir / "a.txt").read_text(encoding="utf-8") == "hello"


def test_move_file(tmp_path):
    src = tmp_path / "b.txt"
    src.write_text("x", encoding="utf-8")
    dst = tmp_path / "moved"
    dst.mkdir()
    resolver = ConflictResolver(MagicMock())
    resolver.overwrite_all = True
    assert move_with_conflict(src, dst, resolver) == "moved"
    assert (dst / "b.txt").is_file()