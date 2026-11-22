"""Find duplicate files by size then hash."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from pycommander.compare_logic import file_hash


def find_duplicates(root: Path) -> dict[str, list[Path]]:
    """Return hash -> list of paths for groups with 2+ files."""
    by_size: dict[int, list[Path]] = defaultdict(list)
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        try:
            by_size[p.stat().st_size].append(p)
        except OSError:
            continue

    dupes: dict[str, list[Path]] = {}
    for size, paths in by_size.items():
        if size == 0 or len(paths) < 2:
            continue
        by_hash: dict[str, list[Path]] = defaultdict(list)
        for p in paths:
            try:
                by_hash[file_hash(p)].append(p)
            except OSError:
                continue
        for h, group in by_hash.items():
            if len(group) >= 2:
                dupes[h] = group
    return dupes