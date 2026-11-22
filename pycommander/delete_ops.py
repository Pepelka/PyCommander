"""Delete to recycle bin or permanent removal."""
from __future__ import annotations

import shutil
from pathlib import Path

try:
    import send2trash
except ImportError:  # pragma: no cover
    send2trash = None


def delete_paths(paths: list[Path], *, permanent: bool = False) -> list[str]:
    """
    Delete files/folders. Returns list of error messages.

    permanent=True uses unlink/rmtree; otherwise send2trash when available.
    """
    errors: list[str] = []
    for p in paths:
        try:
            if permanent or send2trash is None:
                if p.is_dir() and not p.is_symlink():
                    shutil.rmtree(p)
                else:
                    p.unlink(missing_ok=True)
            else:
                send2trash.send2trash(str(p))
        except Exception as e:
            errors.append(f"{p.name}: {e}")
    return errors