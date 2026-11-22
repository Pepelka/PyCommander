"""Shared utilities."""
import os
import string
import datetime
from pathlib import Path

def format_size(size_bytes: int) -> str:
    """Format bytes into human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    for unit in ["KB", "MB", "GB", "TB"]:
        size_bytes /= 1024.0
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
    return f"{size_bytes:.1f} PB"


def get_available_drives() -> list[str]:
    """Return a list of root paths / drives available on the system."""
    if os.name == "nt":
        drives = []
        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            if os.path.exists(drive):
                drives.append(drive)
        return drives or ["C:\\"]
    else:
        roots = ["/", str(Path.home())]
        for mount_dir in ("/Volumes", "/mnt", "/media"):
            if os.path.isdir(mount_dir):
                try:
                    for entry in os.scandir(mount_dir):
                        if entry.is_dir():
                            roots.append(entry.path)
                except PermissionError:
                    pass
        return roots


def format_datetime(ts: float) -> str:
    """Format timestamp as YYYY-MM-DD HH:MM:SS string."""
    if not ts:
        return "Unknown"
    try:
        return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "Unknown"


def get_file_bytes(path: Path) -> bytes:
    from pycommander.archives import find_archive_root, read_archive_file
    """Read bytes from regular file or archive member."""
    arch_info = find_archive_root(path)
    if arch_info:
        return read_archive_file(arch_info[0], arch_info[1])
    return path.read_bytes()


def get_file_text(path: Path) -> str:
    """Read and decode text from regular file or archive member."""
    raw = get_file_bytes(path)
    for enc in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")
