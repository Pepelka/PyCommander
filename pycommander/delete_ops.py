"""Delete to recycle bin or permanent removal."""
from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

try:
    import send2trash
except ImportError:  # pragma: no cover
    send2trash = None


def delete_one_path(path: Path, *, permanent: bool = False) -> str | None:
    """Delete a single path. Returns an error message or None on success."""
    try:
        if permanent or send2trash is None:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
        else:
            send2trash.send2trash(str(path))
    except Exception as e:
        return f"{path.name}: {e}"
    return None


def delete_paths(
    paths: list[Path],
    *,
    permanent: bool = False,
    should_cancel: Callable[[], bool] | None = None,
) -> list[str]:
    """
    Delete files/folders. Returns list of error messages.

    permanent=True uses unlink/rmtree; otherwise send2trash when available.
    """
    errors: list[str] = []
    for p in paths:
        if should_cancel and should_cancel():
            break
        err = delete_one_path(p, permanent=permanent)
        if err:
            errors.append(err)
    return errors