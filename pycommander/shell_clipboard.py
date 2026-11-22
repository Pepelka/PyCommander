"""Windows shell clipboard file list (CF_HDROP) when pywin32 is available."""
from __future__ import annotations

import os
import sys
from pathlib import Path

_WIN = sys.platform == "win32"

try:
    if _WIN:
        import win32clipboard  # type: ignore
        import win32con  # type: ignore
    else:
        win32clipboard = None  # type: ignore
        win32con = None  # type: ignore
except ImportError:
    win32clipboard = None  # type: ignore
    win32con = None  # type: ignore


def clipboard_has_files() -> bool:
    if not _WIN or win32clipboard is None:
        return False
    try:
        win32clipboard.OpenClipboard()
        try:
            return win32clipboard.IsClipboardFormatAvailable(win32con.CF_HDROP)
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        return False


def get_clipboard_file_paths() -> list[Path]:
    if not _WIN or win32clipboard is None:
        return []
    try:
        import struct

        win32clipboard.OpenClipboard()
        try:
            data = win32clipboard.GetClipboardData(win32con.CF_HDROP)
        finally:
            win32clipboard.CloseClipboard()
        # DROPFILES structure: pFiles offset at 0
        offset = struct.unpack_from("I", data, 0)[0]
        raw = data[offset:].decode("utf-16-le", errors="replace")
        parts = [p for p in raw.split("\0") if p]
        return [Path(p) for p in parts if os.path.exists(p)]
    except Exception:
        return []


def set_clipboard_files(paths: list[Path], *, cut: bool = False) -> bool:
    """Place files on clipboard for Explorer paste (best-effort)."""
    if not _WIN or win32clipboard is None or not paths:
        return False
    try:
        # Minimal: use shell via PowerShell Set-Clipboard -Path for copy list
        import subprocess

        plist = ",".join(f"'{p}'" for p in paths)
        mode = "Cut" if cut else "Copy"
        ps = f"$paths = @({plist}); Set-Clipboard -Path $paths"
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            check=True,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        return True
    except Exception:
        return False