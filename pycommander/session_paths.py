"""Restore/save pane locations including paths inside archives."""
from __future__ import annotations

import os
from pathlib import Path

from pycommander.archives import find_archive_root, is_archive_file, list_archive_entries


def is_navigable_path(path: Path) -> bool:
    """True if the pane can open this path (folder, archive file, or path inside archive)."""
    arch = find_archive_root(path)
    if arch:
        arch_path, relpath = arch
        try:
            list_archive_entries(arch_path, relpath)
            return True
        except Exception:
            return False
    try:
        if is_archive_file(path):
            list_archive_entries(path, "")
            return True
    except Exception:
        return False
    try:
        return path.is_dir()
    except OSError:
        return False


def normalize_stored_path(path: Path) -> Path:
    """Load a saved path without breaking archive virtual directories."""
    if find_archive_root(path) is not None or is_archive_file(path):
        return path
    try:
        return path.resolve()
    except OSError:
        return path


def session_start_path(stored: str | None, default: Path) -> Path:
    if not stored or not str(stored).strip():
        return default
    p = Path(os.path.expandvars(os.path.expanduser(str(stored).strip())))
    if is_navigable_path(p):
        return normalize_stored_path(p)
    return default