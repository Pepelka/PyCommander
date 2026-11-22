"""Filesystem search (name and optional content)."""
from __future__ import annotations

from pathlib import Path


def search_files(
    root: Path,
    *,
    name_contains: str = "",
    content_contains: str = "",
    max_content_bytes: int = 256_000,
) -> list[Path]:
    root = root.resolve()
    if not root.is_dir():
        return []
    name_q = name_contains.lower()
    content_q = content_contains.lower()
    hits: list[Path] = []

    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if name_q and name_q not in p.name.lower():
            continue
        if content_q:
            try:
                if p.stat().st_size > max_content_bytes:
                    continue
                text = p.read_bytes()[:max_content_bytes].decode("utf-8", errors="ignore")
                if content_q not in text.lower():
                    continue
            except OSError:
                continue
        hits.append(p)
    return hits