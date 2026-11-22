"""File/folder compare helpers (non-GUI)."""
from __future__ import annotations

import hashlib
from pathlib import Path


def file_hash(path: Path, chunk: int = 65536) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            data = f.read(chunk)
            if not data:
                break
            h.update(data)
    return h.hexdigest()


def files_equal(path_a: Path, path_b: Path) -> bool:
    try:
        if path_a.stat().st_size != path_b.stat().st_size:
            return False
    except OSError:
        return False
    return file_hash(path_a) == file_hash(path_b)


def walk_rel_map(root: Path) -> dict[str, tuple[int, float]]:
    """Map relative path -> (size, mtime) for files under root."""
    out: dict[str, tuple[int, float]] = {}
    root = root.resolve()
    if not root.is_dir():
        return out
    for p in root.rglob("*"):
        if p.is_file():
            rel = str(p.relative_to(root)).replace("\\", "/")
            try:
                st = p.stat()
                out[rel] = (st.st_size, st.st_mtime)
            except OSError:
                pass
    return out


def diff_trees(left: Path, right: Path) -> dict[str, list[str]]:
    """Classify relative paths: only_left, only_right, newer_left, newer_right, same."""
    lm = walk_rel_map(left)
    rm = walk_rel_map(right)
    keys = set(lm) | set(rm)
    result = {
        "only_left": [],
        "only_right": [],
        "newer_left": [],
        "newer_right": [],
        "same": [],
    }
    for k in sorted(keys):
        if k not in rm:
            result["only_left"].append(k)
        elif k not in lm:
            result["only_right"].append(k)
        elif lm[k][1] > rm[k][1] + 1:
            result["newer_left"].append(k)
        elif rm[k][1] > lm[k][1] + 1:
            result["newer_right"].append(k)
        elif lm[k][0] == rm[k][0]:
            result["same"].append(k)
        else:
            result["newer_left"].append(k)
    return result