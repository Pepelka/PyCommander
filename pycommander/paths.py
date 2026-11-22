"""Path metadata helpers."""
import datetime
from pathlib import Path

def get_path_info(p: Path) -> dict:
    """Extract metadata dictionary for a file or directory path."""
    try:
        st = p.stat()
        return {
            "name": p.name,
            "path": str(p),
            "size": st.st_size if not p.is_dir() else 0,
            "mtime": st.st_mtime,
            "is_dir": p.is_dir(),
        }
    except Exception:
        return {
            "name": p.name,
            "path": str(p),
            "size": 0,
            "mtime": 0,
            "is_dir": False,
        }
