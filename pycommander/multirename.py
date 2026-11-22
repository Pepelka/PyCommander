"""Multi-rename pattern expansion."""
from __future__ import annotations

import re
from pathlib import Path


def expand_rename(name: str, pattern: str, index: int) -> str:
    """
    Simple patterns:
      {name}, {stem}, {ext}, {n}, {n:03d}
    """
    p = Path(name)
    stem = p.stem if p.suffix else name
    ext = p.suffix.lstrip(".")
    out = pattern
    out = out.replace("{name}", name)
    out = out.replace("{stem}", stem)
    out = out.replace("{ext}", ext)
    out = out.replace("{n}", str(index))

    def pad_sub(m):
        width = int(m.group(1))
        return str(index).zfill(width)

    out = re.sub(r"\{n:(\d+)d\}", pad_sub, out)
    return out


def preview_renames(names: list[str], pattern: str) -> list[tuple[str, str]]:
    return [(n, expand_rename(n, pattern, i + 1)) for i, n in enumerate(names)]


def regex_rename(name: str, pattern: str, replacement: str) -> str:
    return re.sub(pattern, replacement, name)