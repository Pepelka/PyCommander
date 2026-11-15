#!/usr/bin/env python3
"""
PyCommander - A dual-pane file manager inspired by Total Commander.
Uses only Python standard library modules (tkinter, os, shutil, pathlib, etc.).
"""

import os
import sys
import shutil
import stat
import subprocess
import threading
import datetime
import string
import zipfile
import tarfile
import difflib
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
from pathlib import Path


ARCHIVE_EXTENSIONS = (
    ".zip", ".jar", ".war", ".whl",
    ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz"
)


def is_archive_file(path: Path) -> bool:
    """Check if the given path is a supported archive file."""
    try:
        if not path.is_file():
            return False
        name = path.name.lower()
        if any(name.endswith(ext) for ext in ARCHIVE_EXTENSIONS):
            return zipfile.is_zipfile(str(path)) or tarfile.is_tarfile(str(path))
        return False
    except OSError:
        return False


def find_archive_root(path: Path) -> tuple[Path, str] | None:
    """
    Check if `path` is an archive file or points inside an archive.
    Returns (archive_file_path, internal_relpath) or None.
    """
    cur = path
    sub_parts = []
    while True:
        try:
            if cur.is_file() and is_archive_file(cur):
                rel = "/".join(reversed(sub_parts))
                return (cur.resolve(), rel)
        except OSError:
            pass
        if cur.parent == cur:
            break
        sub_parts.append(cur.name)
        cur = cur.parent
    return None


def list_archive_entries(archive_path: Path, relpath: str = "") -> list[dict]:
    """List direct children inside an archive at `relpath`."""
    relpath = relpath.strip("/").replace("\\", "/")
    entries: dict[str, dict] = {}

    if zipfile.is_zipfile(str(archive_path)):
        with zipfile.ZipFile(archive_path, "r") as zf:
            for info in zf.infolist():
                fn = info.filename.strip("/").replace("\\", "/")
                if not fn:
                    continue
                if relpath:
                    if not (fn == relpath or fn.startswith(relpath + "/")):
                        continue
                    if fn == relpath:
                        continue
                    sub = fn[len(relpath) + 1 :]
                else:
                    sub = fn

                parts = sub.split("/")
                item_name = parts[0]
                is_dir = len(parts) > 1 or info.is_dir()
                try:
                    mtime = datetime.datetime(*info.date_time).timestamp()
                except Exception:
                    mtime = 0

                if item_name not in entries or (is_dir and not entries[item_name]["is_dir"]):
                    entries[item_name] = {
                        "name": item_name,
                        "is_dir": is_dir,
                        "size": 0 if is_dir else info.file_size,
                        "mtime": mtime,
                        "is_archive": False,
                    }
    elif tarfile.is_tarfile(str(archive_path)):
        with tarfile.open(archive_path, "r:*") as tf:
            for m in tf.getmembers():
                fn = m.name.lstrip("./").strip("/").replace("\\", "/")
                if not fn:
                    continue
                if relpath:
                    if not (fn == relpath or fn.startswith(relpath + "/")):
                        continue
                    if fn == relpath:
                        continue
                    sub = fn[len(relpath) + 1 :]
                else:
                    sub = fn

                parts = sub.split("/")
                item_name = parts[0]
                is_dir = len(parts) > 1 or m.isdir()
                if item_name not in entries or (is_dir and not entries[item_name]["is_dir"]):
                    entries[item_name] = {
                        "name": item_name,
                        "is_dir": is_dir,
                        "size": 0 if is_dir else m.size,
                        "mtime": m.mtime,
                        "is_archive": False,
                    }
    return list(entries.values())


def read_archive_file(archive_path: Path, relpath: str) -> bytes:
    """Read full raw bytes of an entry inside an archive."""
    relpath = relpath.strip("/").replace("\\", "/")
    if zipfile.is_zipfile(str(archive_path)):
        with zipfile.ZipFile(archive_path, "r") as zf:
            return zf.read(relpath)
    elif tarfile.is_tarfile(str(archive_path)):
        with tarfile.open(archive_path, "r:*") as tf:
            f = tf.extractfile(relpath)
            if f is None:
                raise FileNotFoundError(f"Not a regular file in archive: {relpath}")
            return f.read()
    raise ValueError(f"Unsupported archive format: {archive_path}")


def extract_archive_item(archive_path: Path, relpath: str, dest_dir: Path, resolver: "ConflictResolver | None" = None) -> bool:
    """Extract an archive file or directory into `dest_dir` with conflict resolution."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    relpath = relpath.strip("/").replace("\\", "/")

    if zipfile.is_zipfile(str(archive_path)):
        with zipfile.ZipFile(archive_path, "r") as zf:
            matching = [info for info in zf.infolist() if info.filename.strip("/").replace("\\", "/") == relpath]
            if matching and not matching[0].is_dir():
                out_path = dest_dir / Path(relpath).name
                if out_path.exists():
                    if resolver:
                        mtime = (
                            datetime.datetime(*matching[0].date_time).timestamp()
                            if matching[0].date_time
                            else 0
                        )
                        src_info = {
                            "name": out_path.name,
                            "path": f"{archive_path.name}/{relpath}",
                            "size": matching[0].file_size,
                            "mtime": mtime,
                            "is_dir": False,
                        }
                        dst_info = get_path_info(out_path)
                        act = resolver.resolve(src_info, dst_info, out_path)
                        if act == "cancel":
                            return False
                        elif act == "skip":
                            return True
                    try:
                        os.chmod(out_path, stat.S_IWRITE | stat.S_IREAD)
                    except Exception:
                        pass
                with zf.open(matching[0]) as source, open(out_path, "wb") as target:
                    target.write(source.read())
                return True

            prefix = relpath + "/" if relpath else ""
            base_folder = Path(relpath).name if relpath else ""
            for info in zf.infolist():
                if resolver and resolver.cancelled:
                    return False
                fn = info.filename.strip("/").replace("\\", "/")
                if prefix and not fn.startswith(prefix):
                    continue
                sub_rel = fn[len(prefix) :] if prefix else fn
                if not sub_rel:
                    continue
                target_path = dest_dir / base_folder / Path(sub_rel) if base_folder else dest_dir / Path(sub_rel)
                if info.is_dir():
                    target_path.mkdir(parents=True, exist_ok=True)
                else:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    if target_path.exists():
                        if resolver:
                            mtime = (
                                datetime.datetime(*info.date_time).timestamp()
                                if info.date_time
                                else 0
                            )
                            src_info = {
                                "name": target_path.name,
                                "path": f"{archive_path.name}/{info.filename}",
                                "size": info.file_size,
                                "mtime": mtime,
                                "is_dir": False,
                            }
                            dst_info = get_path_info(target_path)
                            act = resolver.resolve(src_info, dst_info, target_path)
                            if act == "cancel":
                                return False
                            elif act == "skip":
                                continue
                        try:
                            os.chmod(target_path, stat.S_IWRITE | stat.S_IREAD)
                        except Exception:
                            pass
                    with zf.open(info) as src, open(target_path, "wb") as dst:
                        dst.write(src.read())
            return True
    elif tarfile.is_tarfile(str(archive_path)):
        with tarfile.open(archive_path, "r:*") as tf:
            matching = [m for m in tf.getmembers() if m.name.lstrip("./").strip("/").replace("\\", "/") == relpath]
            if matching and not matching[0].isdir():
                out_path = dest_dir / Path(relpath).name
                if out_path.exists():
                    if resolver:
                        src_info = {
                            "name": out_path.name,
                            "path": f"{archive_path.name}/{relpath}",
                            "size": matching[0].size,
                            "mtime": matching[0].mtime,
                            "is_dir": False,
                        }
                        dst_info = get_path_info(out_path)
                        act = resolver.resolve(src_info, dst_info, out_path)
                        if act == "cancel":
                            return False
                        elif act == "skip":
                            return True
                    try:
                        os.chmod(out_path, stat.S_IWRITE | stat.S_IREAD)
                    except Exception:
                        pass
                f = tf.extractfile(matching[0])
                if f:
                    with open(out_path, "wb") as target:
                        target.write(f.read())
                return True

            prefix = relpath + "/" if relpath else ""
            base_folder = Path(relpath).name if relpath else ""
            for m in tf.getmembers():
                if resolver and resolver.cancelled:
                    return False
                fn = m.name.lstrip("./").strip("/").replace("\\", "/")
                if prefix and not fn.startswith(prefix):
                    continue
                sub_rel = fn[len(prefix) :] if prefix else fn
                if not sub_rel:
                    continue
                target_path = dest_dir / base_folder / Path(sub_rel) if base_folder else dest_dir / Path(sub_rel)
                if m.isdir():
                    target_path.mkdir(parents=True, exist_ok=True)
                else:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    if target_path.exists():
                        if resolver:
                            src_info = {
                                "name": target_path.name,
                                "path": f"{archive_path.name}/{m.name}",
                                "size": m.size,
                                "mtime": m.mtime,
                                "is_dir": False,
                            }
                            dst_info = get_path_info(target_path)
                            act = resolver.resolve(src_info, dst_info, target_path)
                            if act == "cancel":
                                return False
                            elif act == "skip":
                                continue
                        try:
                            os.chmod(target_path, stat.S_IWRITE | stat.S_IREAD)
                        except Exception:
                            pass
                    f = tf.extractfile(m)
                    if f:
                        with open(target_path, "wb") as dst:
                            dst.write(f.read())
            return True
    return False


def get_file_bytes(path: Path) -> bytes:
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


class OverwriteConfirmDialog(tk.Toplevel):
    """Modal dialog prompting user what to do when a destination file already exists."""

    def __init__(self, parent, src_info: dict, dst_info: dict, dst_path: Path):
        super().__init__(parent)
        self.title("Confirm File Overwrite")
        self.result = "cancel"
        self.resizable(False, False)

        self.transient(parent)
        self.grab_set()

        bold_font = ("Segoe UI", 9, "bold")
        heading_font = ("Segoe UI", 11, "bold")
        normal_font = ("Segoe UI", 9)
        small_font = ("Segoe UI", 8)

        main_frame = ttk.Frame(self, padding="16 16 16 16")
        main_frame.pack(fill=tk.BOTH, expand=True)

        top_frame = ttk.Frame(main_frame)
        top_frame.pack(fill=tk.X, pady=(0, 10))

        warning_icon = tk.Label(top_frame, text="⚠️", font=("Segoe UI", 24))
        warning_icon.pack(side=tk.LEFT, padx=(0, 12))

        text_frame = ttk.Frame(top_frame)
        text_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

        lbl_head = ttk.Label(text_frame, text="File already exists!", font=heading_font)
        lbl_head.pack(anchor=tk.W)

        lbl_sub = ttk.Label(
            text_frame,
            text=f"The destination file already exists:\n{dst_path.name}",
            font=bold_font,
            foreground="#c00000",
        )
        lbl_sub.pack(anchor=tk.W, pady=(2, 0))

        lbl_dest = ttk.Label(
            main_frame,
            text=f"In directory: {dst_path.parent}",
            font=small_font,
            foreground="#555555",
        )
        lbl_dest.pack(anchor=tk.W, pady=(0, 8))

        comp_frame = ttk.LabelFrame(main_frame, text=" File Comparison ", padding="10 10 10 10")
        comp_frame.pack(fill=tk.X, pady=(0, 10))

        # Left Column: Source File
        src_box = ttk.Frame(comp_frame)
        src_box.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        ttk.Label(src_box, text="Source (New):", font=bold_font, foreground="#004e98").pack(anchor=tk.W)
        src_sz = src_info.get("size", 0)
        src_size_str = format_size(src_sz)
        src_bytes_str = f"{src_sz:,} bytes"
        src_date_str = format_datetime(src_info.get("mtime", 0))

        ttk.Label(src_box, text=f"Size: {src_bytes_str} ({src_size_str})", font=normal_font).pack(anchor=tk.W, pady=(2, 0))
        ttk.Label(src_box, text=f"Modified: {src_date_str}", font=normal_font).pack(anchor=tk.W)
        if src_info.get("path"):
            short_src = str(src_info["path"])
            if len(short_src) > 42:
                short_src = "..." + short_src[-39:]
            ttk.Label(src_box, text=f"From: {short_src}", font=small_font, foreground="#666666").pack(anchor=tk.W, pady=(2, 0))

        sep = ttk.Separator(comp_frame, orient=tk.VERTICAL)
        sep.grid(row=0, column=1, sticky="ns", padx=5)

        # Right Column: Existing File
        dst_box = ttk.Frame(comp_frame)
        dst_box.grid(row=0, column=2, sticky="nsew", padx=(10, 0))

        ttk.Label(dst_box, text="Existing (Destination):", font=bold_font, foreground="#b71c1c").pack(anchor=tk.W)
        dst_sz = dst_info.get("size", 0)
        dst_size_str = format_size(dst_sz)
        dst_bytes_str = f"{dst_sz:,} bytes"
        dst_date_str = format_datetime(dst_info.get("mtime", 0))

        ttk.Label(dst_box, text=f"Size: {dst_bytes_str} ({dst_size_str})", font=normal_font).pack(anchor=tk.W, pady=(2, 0))
        ttk.Label(dst_box, text=f"Modified: {dst_date_str}", font=normal_font).pack(anchor=tk.W)
        short_dst = str(dst_path)
        if len(short_dst) > 42:
            short_dst = "..." + short_dst[-39:]
        ttk.Label(dst_box, text=f"At: {short_dst}", font=small_font, foreground="#666666").pack(anchor=tk.W, pady=(2, 0))

        comp_frame.columnconfigure(0, weight=1)
        comp_frame.columnconfigure(2, weight=1)

        hints = []
        src_mtime = src_info.get("mtime", 0)
        dst_mtime = dst_info.get("mtime", 0)
        if src_mtime and dst_mtime:
            time_diff = src_mtime - dst_mtime
            if abs(time_diff) < 2:
                hints.append("Same modification date")
            elif time_diff > 0:
                hints.append("Source file is NEWER")
            else:
                hints.append("Source file is OLDER")

        if src_sz > dst_sz:
            hints.append("LARGER")
        elif src_sz < dst_sz:
            hints.append("SMALLER")
        else:
            hints.append("same size")

        if hints:
            hint_text = " • ".join(hints)
            hint_lbl = tk.Label(
                main_frame,
                text=f"Comparison: {hint_text}",
                font=bold_font,
                bg="#fff8e1",
                fg="#f57f17",
                relief=tk.SOLID,
                bd=1,
                padx=8,
                pady=4,
            )
            hint_lbl.pack(fill=tk.X, pady=(0, 12))

        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X)

        btn_ovw = ttk.Button(btn_frame, text="Overwrite (O)", command=lambda: self.set_result("overwrite"))
        btn_ovw.pack(side=tk.LEFT, padx=(0, 4))

        btn_ovw_all = ttk.Button(btn_frame, text="Overwrite All (A)", command=lambda: self.set_result("overwrite_all"))
        btn_ovw_all.pack(side=tk.LEFT, padx=4)

        btn_skip = ttk.Button(btn_frame, text="Skip (S)", command=lambda: self.set_result("skip"))
        btn_skip.pack(side=tk.LEFT, padx=4)

        btn_skip_all = ttk.Button(btn_frame, text="Skip All (K)", command=lambda: self.set_result("skip_all"))
        btn_skip_all.pack(side=tk.LEFT, padx=4)

        btn_cancel = ttk.Button(btn_frame, text="Cancel (Esc)", command=lambda: self.set_result("cancel"))
        btn_cancel.pack(side=tk.RIGHT, padx=(4, 0))

        # Hotkeys
        self.bind("<Return>", lambda e: self.set_result("overwrite"))
        self.bind("<Escape>", lambda e: self.set_result("cancel"))
        self.bind("<Alt-o>", lambda e: self.set_result("overwrite"))
        self.bind("<Alt-O>", lambda e: self.set_result("overwrite"))
        self.bind("<Alt-a>", lambda e: self.set_result("overwrite_all"))
        self.bind("<Alt-A>", lambda e: self.set_result("overwrite_all"))
        self.bind("<Alt-s>", lambda e: self.set_result("skip"))
        self.bind("<Alt-S>", lambda e: self.set_result("skip"))
        self.bind("<Alt-k>", lambda e: self.set_result("skip_all"))
        self.bind("<Alt-K>", lambda e: self.set_result("skip_all"))
        self.bind("<Alt-c>", lambda e: self.set_result("cancel"))
        self.bind("<Alt-C>", lambda e: self.set_result("cancel"))
        self.protocol("WM_DELETE_WINDOW", lambda: self.set_result("cancel"))

        btn_ovw.focus_set()

        self.update_idletasks()
        try:
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            w = self.winfo_width()
            h = self.winfo_height()
            cx = max(0, px + (pw - w) // 2)
            cy = max(0, py + (ph - h) // 2)
            self.geometry(f"+{cx}+{cy}")
        except Exception:
            pass

    def set_result(self, res: str):
        self.result = res
        self.destroy()


class ConflictResolver:
    """Manages overwrite confirmation state across a batch file operation."""

    def __init__(self, parent):
        self.parent = parent
        self.overwrite_all = False
        self.skip_all = False
        self.cancelled = False

    def resolve(self, src_info: dict, dst_info: dict, dst_path: Path) -> str:
        """
        Returns:
            'overwrite' - overwrite this item
            'skip'      - skip this item
            'cancel'    - abort entire operation
        """
        if self.cancelled:
            return "cancel"
        if self.skip_all:
            return "skip"
        if self.overwrite_all:
            return "overwrite"

        dlg = OverwriteConfirmDialog(self.parent, src_info, dst_info, dst_path)
        dlg.wait_window()
        res = getattr(dlg, "result", "cancel")

        if res == "cancel" or not res:
            self.cancelled = True
            return "cancel"
        elif res == "overwrite_all":
            self.overwrite_all = True
            return "overwrite"
        elif res == "skip_all":
            self.skip_all = True
            return "skip"
        elif res == "overwrite":
            return "overwrite"
        elif res == "skip":
            return "skip"
        return "skip"


def copy_file_with_conflict(src: Path, dst: Path, resolver: ConflictResolver) -> str:
    """
    Copy a single file from src to dst respecting conflict resolution.
    Returns: 'copied', 'skipped', or 'cancelled'.
    """
    if resolver.cancelled:
        return "cancelled"

    target_file = dst / src.name if dst.is_dir() else dst

    try:
        if src.resolve() == target_file.resolve():
            return "skipped"
    except Exception:
        pass

    if target_file.exists():
        src_info = get_path_info(src)
        dst_info = get_path_info(target_file)
        action = resolver.resolve(src_info, dst_info, target_file)
        if action == "cancel":
            return "cancelled"
        elif action == "skip":
            return "skipped"

        # Overwrite
        try:
            os.chmod(target_file, stat.S_IWRITE | stat.S_IREAD)
        except Exception:
            pass
        shutil.copy2(src, target_file)
        return "copied"
    else:
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target_file)
        return "copied"


def copy_dir_with_conflict(src_dir: Path, dst_dir: Path, resolver: ConflictResolver) -> str:
    """
    Recursively copy directory contents respecting conflict resolution.
    Returns: 'copied', 'skipped', or 'cancelled'.
    """
    if resolver.cancelled:
        return "cancelled"

    dst_dir.mkdir(parents=True, exist_ok=True)
    for entry in src_dir.iterdir():
        if resolver.cancelled:
            return "cancelled"
        target = dst_dir / entry.name
        if entry.is_dir():
            res = copy_dir_with_conflict(entry, target, resolver)
            if res == "cancelled":
                return "cancelled"
        else:
            res = copy_file_with_conflict(entry, target, resolver)
            if res == "cancelled":
                return "cancelled"
    return "copied"


def move_with_conflict(src: Path, dst: Path, resolver: ConflictResolver) -> str:
    """
    Move src to dst respecting conflict resolution.
    Returns: 'moved', 'skipped', or 'cancelled'.
    """
    if resolver.cancelled:
        return "cancelled"

    target = dst / src.name if dst.is_dir() and not (dst.exists() and src.is_dir() and dst.name == src.name) else dst

    try:
        if src.resolve() == target.resolve():
            return "skipped"
    except Exception:
        pass

    if target.exists():
        src_info = get_path_info(src)
        dst_info = get_path_info(target)
        action = resolver.resolve(src_info, dst_info, target)
        if action == "cancel":
            return "cancelled"
        elif action == "skip":
            return "skipped"

        # Overwrite
        if target.is_dir() and src.is_dir():
            res = copy_dir_with_conflict(src, target, resolver)
            if res == "cancelled":
                return "cancelled"
            shutil.rmtree(src, ignore_errors=True)
            return "moved"
        else:
            try:
                os.chmod(target, stat.S_IWRITE | stat.S_IREAD)
                if target.is_file():
                    target.unlink()
                elif target.is_dir():
                    shutil.rmtree(target, ignore_errors=True)
            except Exception:
                pass
            shutil.move(str(src), str(target))
            return "moved"
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(target))
        return "moved"


class FilePane(ttk.Frame):
    """Represents one side (left or right) of the dual-pane file browser."""

    def __init__(self, parent, app, initial_path: Path):
        super().__init__(parent, padding=3)
        self.app = app
        self.current_path = initial_path.resolve()
        self.sort_col = "name"
        self.sort_reverse = False
        self.is_active = False
        self.marked_items: set[str] = set()

        # Path history tracking
        self.history_stack: list[Path] = [self.current_path]
        self.history_index: int = 0
        self.path_history: list[Path] = [self.current_path]

        self._build_ui()
        self._update_history_buttons()
        self.refresh()

    def _build_ui(self):
        # Top bar: Drive selector, Back/Forward, Path entry, History, Up button, Refresh button
        top_bar = ttk.Frame(self)
        top_bar.pack(fill=tk.X, pady=(0, 3))

        drives = get_available_drives()
        self.drive_var = tk.StringVar()
        self.drive_combo = ttk.Combobox(
            top_bar, textvariable=self.drive_var, values=drives, width=6, state="readonly"
        )
        self.drive_combo.pack(side=tk.LEFT, padx=(0, 2))
        self.drive_combo.bind("<<ComboboxSelected>>", self._on_drive_selected)

        self.back_btn = ttk.Button(top_bar, text="◀", width=3, command=self.history_back)
        self.back_btn.pack(side=tk.LEFT, padx=(0, 1))

        self.fwd_btn = ttk.Button(top_bar, text="▶", width=3, command=self.history_forward)
        self.fwd_btn.pack(side=tk.LEFT, padx=(0, 2))

        self.path_var = tk.StringVar(value=str(self.current_path))
        self.path_entry = tk.Entry(
            top_bar,
            textvariable=self.path_var,
            font=("Consolas", 10),
            relief=tk.FLAT,
            bd=2,
        )
        self.path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
        self.path_entry.bind("<Return>", self._on_path_entered)
        self.path_entry.bind("<FocusIn>", lambda e: self.app.set_active_pane(self))
        self.path_entry.bind("<Alt-Down>", self.show_history_menu)
        self.path_entry.bind("<Down>", self._on_path_entry_down)

        self.hist_btn = ttk.Button(top_bar, text="▾", width=3, command=self.show_history_menu)
        self.hist_btn.pack(side=tk.LEFT, padx=(0, 2))

        up_btn = ttk.Button(top_bar, text="..", width=3, command=self.go_up)
        up_btn.pack(side=tk.LEFT, padx=(0, 2))

        refresh_btn = ttk.Button(top_bar, text="⟳", width=3, command=self.refresh)
        refresh_btn.pack(side=tk.LEFT)

        # Middle: Treeview + Scrollbar
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("name", "ext", "size", "date")
        self.tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", selectmode="extended"
        )

        self.tree.heading("name", text="Name ▲", anchor=tk.W, command=lambda: self.sort_by("name"))
        self.tree.heading("ext", text="Ext", anchor=tk.W, command=lambda: self.sort_by("ext"))
        self.tree.heading("size", text="Size", anchor=tk.E, command=lambda: self.sort_by("size"))
        self.tree.heading("date", text="Modified", anchor=tk.W, command=lambda: self.sort_by("date"))

        self.tree.column("name", width=220, minwidth=100, anchor=tk.W, stretch=True)
        self.tree.column("ext", width=60, minwidth=40, anchor=tk.W, stretch=False)
        self.tree.column("size", width=85, minwidth=60, anchor=tk.E, stretch=False)
        self.tree.column("date", width=130, minwidth=90, anchor=tk.W, stretch=False)

        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # Tag styles for directories and marked items
        self.tree.tag_configure("dir", font=("Segoe UI", 9, "bold"))
        self.tree.tag_configure("file", font=("Segoe UI", 9))
        self.tree.tag_configure("archive", font=("Segoe UI", 9, "bold"), foreground="#6a1b9a")
        self.tree.tag_configure("marked_dir", font=("Segoe UI", 9, "bold"), foreground="#c00000", background="#fff4cc")
        self.tree.tag_configure("marked_file", font=("Segoe UI", 9, "bold"), foreground="#c00000", background="#fff4cc")
        self.tree.tag_configure("marked_archive", font=("Segoe UI", 9, "bold"), foreground="#c00000", background="#fff4cc")

        # Bindings
        self.tree.bind("<FocusIn>", lambda e: self.app.set_active_pane(self))
        self.tree.bind("<Button-1>", lambda e: self.app.set_active_pane(self))
        self.tree.bind("<Double-1>", self._on_activate_item)
        self.tree.bind("<Return>", self._on_activate_item)
        self.tree.bind("<BackSpace>", lambda e: self.go_up())
        self.tree.bind("<Tab>", self._on_tab_key)
        self.tree.bind("<Insert>", self._on_insert_key)
        self.tree.bind("<space>", self._on_space_key)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.update_status())

        # Bottom status label
        self.status_var = tk.StringVar(value="")
        self.status_lbl = ttk.Label(self, textvariable=self.status_var, anchor=tk.W)
        self.status_lbl.pack(fill=tk.X, pady=(2, 0))

    def set_active_visual(self, active: bool):
        self.is_active = active
        if active:
            self.path_entry.configure(bg="#004e98", fg="white", insertbackground="white")
        else:
            self.path_entry.configure(bg="#e0e0e0", fg="#333333", insertbackground="black")

    def _on_tab_key(self, event):
        self.app.switch_pane()
        return "break"

    def is_dir(self, path: Path) -> bool:
        """Check if path is a folder (on real filesystem or inside an archive)."""
        arch_info = find_archive_root(path)
        if arch_info is None:
            return path.is_dir()
        arch_path, relpath = arch_info
        if not relpath:
            return True
        parent_rel = str(Path(relpath).parent).replace("\\", "/")
        if parent_rel == ".":
            parent_rel = ""
        entries = list_archive_entries(arch_path, parent_rel)
        name = Path(relpath).name
        for e in entries:
            if e["name"] == name:
                return e["is_dir"]
        return False

    def _update_item_visual(self, iid: str):
        if iid == ".." or not self.tree.exists(iid):
            return
        item_path = self.current_path / iid
        is_directory = self.is_dir(item_path)
        is_arch = not is_directory and is_archive_file(item_path)
        marked = iid in self.marked_items
        if is_directory:
            disp_name = f"☑ 📁 [{iid}]" if marked else f"📁 [{iid}]"
            tag = "marked_dir" if marked else "dir"
        elif is_arch:
            disp_name = f"☑ 📦 [{iid}]" if marked else f"📦 [{iid}]"
            tag = "marked_archive" if marked else "archive"
        else:
            p = Path(iid)
            stem = p.stem if p.suffix else iid
            disp_name = f"☑ 📄 {stem}" if marked else f"📄 {stem}"
            tag = "marked_file" if marked else "file"

        vals = list(self.tree.item(iid, "values"))
        if vals:
            vals[0] = disp_name
            self.tree.item(iid, values=vals, tags=(tag,))

    def toggle_mark(self, iid: str):
        if not iid or iid == "..":
            return
        if iid in self.marked_items:
            self.marked_items.remove(iid)
        else:
            self.marked_items.add(iid)
        self._update_item_visual(iid)
        self.update_status()

    def _on_insert_key(self, event):
        """Toggle mark of focused item and move cursor down (classic Commander behavior)."""
        focus_id = self.tree.focus()
        if not focus_id:
            sel = self.tree.selection()
            focus_id = sel[0] if sel else None
        if focus_id:
            self.toggle_mark(focus_id)
            next_id = self.tree.next(focus_id)
            target_id = next_id if next_id else focus_id
            self.tree.focus(target_id)
            self.tree.selection_set(target_id)
            self.tree.see(target_id)
        return "break"

    def _on_space_key(self, event):
        """Toggle mark of focused item without moving cursor."""
        focus_id = self.tree.focus()
        if not focus_id:
            sel = self.tree.selection()
            focus_id = sel[0] if sel else None
        if focus_id:
            self.toggle_mark(focus_id)
        return "break"

    def _on_drive_selected(self, event=None):
        drive = self.drive_var.get()
        if drive:
            self.navigate_to(Path(drive))

    def _on_path_entered(self, event=None):
        raw = self.path_var.get().strip()
        target = Path(os.path.expandvars(os.path.expanduser(raw)))
        if target.is_dir() or is_archive_file(target) or find_archive_root(target):
            self.navigate_to(target)
        else:
            messagebox.showerror("Invalid Path", f"Directory or archive does not exist:\n{target}")
            self.path_var.set(str(self.current_path))
        self.tree.focus_set()

    def history_back(self):
        if self.history_index > 0:
            self.history_index -= 1
            target = self.history_stack[self.history_index]
            self.navigate_to(target, record_history=False)

    def history_forward(self):
        if self.history_index < len(self.history_stack) - 1:
            self.history_index += 1
            target = self.history_stack[self.history_index]
            self.navigate_to(target, record_history=False)

    def _update_history_buttons(self):
        can_back = self.history_index > 0
        can_fwd = self.history_index < len(self.history_stack) - 1
        self.back_btn.configure(state="normal" if can_back else "disabled")
        self.fwd_btn.configure(state="normal" if can_fwd else "disabled")

    def _on_path_entry_down(self, event):
        self.show_history_menu()
        return "break"

    def show_history_menu(self, event=None):
        if not self.path_history:
            return "break"
        menu = tk.Menu(self, tearoff=0)
        for p in self.path_history:
            is_cur = (p == self.current_path)
            prefix = "✓ " if is_cur else "   "
            menu.add_command(
                label=f"{prefix}{p}",
                command=lambda target=p: self.navigate_to(target),
            )
        menu.add_separator()
        menu.add_command(label="Clear Path History", command=self.clear_history)

        x = self.path_entry.winfo_rootx()
        y = self.path_entry.winfo_rooty() + self.path_entry.winfo_height()
        menu.tk_popup(x, y)
        return "break"

    def clear_history(self):
        self.path_history = [self.current_path]
        self.history_stack = [self.current_path]
        self.history_index = 0
        self._update_history_buttons()

    def navigate_to(
        self, path: Path, select_name: str | None = None, record_history: bool = True
    ):
        arch_info = find_archive_root(path)
        if arch_info:
            arch_path, relpath = arch_info
            try:
                list_archive_entries(arch_path, relpath)
            except Exception as e:
                messagebox.showerror("Archive Error", f"Cannot open archive directory:\n{e}")
                return
            resolved = path
        else:
            try:
                resolved = path.resolve()
                # Test read access before switching
                list(os.scandir(resolved))
            except PermissionError:
                messagebox.showwarning("Access Denied", f"Permission denied:\n{path}")
                return
            except Exception as e:
                messagebox.showerror("Error", f"Cannot open directory:\n{e}")
                return

        prev_path = self.current_path
        self.current_path = resolved
        self.marked_items.clear()

        # Update path history list (most recent first, unique)
        if resolved in self.path_history:
            self.path_history.remove(resolved)
        self.path_history.insert(0, resolved)
        if len(self.path_history) > 30:
            self.path_history.pop()

        # Update back/forward history stack
        if record_history and resolved != prev_path:
            self.history_stack = self.history_stack[: self.history_index + 1]
            self.history_stack.append(resolved)
            self.history_index = len(self.history_stack) - 1

        self._update_history_buttons()
        self.refresh(select_name=select_name)

    def go_up(self):
        parent = self.current_path.parent
        if parent != self.current_path:
            prev_name = self.current_path.name
            self.navigate_to(parent, select_name=prev_name)

    def sort_by(self, col: str):
        if self.sort_col == col:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_col = col
            self.sort_reverse = False
        self._update_heading_arrows()
        self.refresh()

    def _update_heading_arrows(self):
        titles = {"name": "Name", "ext": "Ext", "size": "Size", "date": "Modified"}
        for col, label in titles.items():
            if col == self.sort_col:
                arrow = " ▼" if self.sort_reverse else " ▲"
                self.tree.heading(col, text=label + arrow)
            else:
                self.tree.heading(col, text=label)

    def refresh(self, select_name: str | None = None, preserve_focus: bool = True):
        # Capture scroll position and current focus BEFORE wiping the tree
        scroll_top, scroll_bot = self.tree.yview()
        prev_focus = self.tree.focus() if preserve_focus else None
        self.path_var.set(str(self.current_path))
        arch_info = find_archive_root(self.current_path)
        drive_path = arch_info[0] if arch_info else self.current_path
        if os.name == "nt" and drive_path.drive:
            self.drive_var.set(drive_path.drive + "\\")

        self.tree.delete(*self.tree.get_children())

        entries = []
        if arch_info:
            try:
                raw_entries = list_archive_entries(arch_info[0], arch_info[1])
                for item in raw_entries:
                    is_dir = item["is_dir"]
                    p = Path(item["name"])
                    stem = p.stem if (p.suffix and not is_dir) else item["name"]
                    ext = p.suffix[1:] if (p.suffix and not is_dir) else ""
                    entries.append({
                        "name": item["name"],
                        "stem": stem,
                        "ext": ext,
                        "size": item["size"],
                        "mtime": item["mtime"],
                        "is_dir": is_dir,
                        "is_archive": False,
                        "path": self.current_path / item["name"],
                    })
            except Exception:
                pass
        else:
            try:
                with os.scandir(self.current_path) as it:
                    for entry in it:
                        try:
                            is_dir = entry.is_dir()
                            st = entry.stat()
                            mtime = st.st_mtime
                            size = 0 if is_dir else st.st_size
                        except OSError:
                            is_dir = False
                            mtime = 0
                            size = 0

                        is_arch = not is_dir and is_archive_file(Path(entry.path))
                        if is_dir:
                            stem = entry.name
                            ext = ""
                        else:
                            p = Path(entry.name)
                            stem = p.stem if p.suffix else entry.name
                            ext = p.suffix[1:] if p.suffix else ""

                        entries.append({
                            "name": entry.name,
                            "stem": stem,
                            "ext": ext,
                            "size": size,
                            "mtime": mtime,
                            "is_dir": is_dir,
                            "is_archive": is_arch,
                            "path": Path(entry.path),
                        })
            except PermissionError:
                pass

        # Keep only marks for entries that still exist
        existing_names = {e["name"] for e in entries}
        self.marked_items &= existing_names

        # Sort directories and files separately so directories always stay on top
        dirs = [e for e in entries if e["is_dir"]]
        files = [e for e in entries if not e["is_dir"]]

        key_map = {
            "name": lambda x: x["name"].lower(),
            "ext": lambda x: (x["ext"].lower(), x["name"].lower()),
            "size": lambda x: (x["size"], x["name"].lower()),
            "date": lambda x: (x["mtime"], x["name"].lower()),
        }
        key_fn = key_map.get(self.sort_col, key_map["name"])
        dirs.sort(key=key_fn, reverse=self.sort_reverse)
        files.sort(key=key_fn, reverse=self.sort_reverse)

        target_iid = None

        # Add parent directory ".." if not at root
        if self.current_path.parent != self.current_path:
            iid = self.tree.insert(
                "", tk.END, iid="..", values=("📁 [..]", "", "<DIR>", ""), tags=("dir",)
            )
            # Only pre-select ".." as fallback if we have no other preference
            if not prev_focus or prev_focus == "..":
                target_iid = iid

        for item in dirs + files:
            dt_str = (
                datetime.datetime.fromtimestamp(item["mtime"]).strftime("%Y-%m-%d %H:%M")
                if item["mtime"]
                else ""
            )
            marked = item["name"] in self.marked_items
            if item["is_dir"]:
                disp_name = f"☑ 📁 [{item['name']}]" if marked else f"📁 [{item['name']}]"
                disp_size = "<DIR>"
                tag = "marked_dir" if marked else "dir"
            elif item.get("is_archive"):
                disp_name = f"☑ 📦 [{item['name']}]" if marked else f"📦 [{item['name']}]"
                disp_size = format_size(item["size"])
                tag = "marked_archive" if marked else "archive"
            else:
                disp_name = f"☑ 📄 {item['stem']}" if marked else f"📄 {item['stem']}"
                disp_size = format_size(item["size"])
                tag = "marked_file" if marked else "file"

            iid = item["name"]
            self.tree.insert(
                "",
                tk.END,
                iid=iid,
                values=(disp_name, item["ext"], disp_size, dt_str),
                tags=(tag,),
            )
            # Priority 1: explicit select_name wins
            if select_name and item["name"] == select_name:
                target_iid = iid
            # Priority 2: restore previous focus (only if select_name is not set)
            elif not select_name and prev_focus and item["name"] == prev_focus:
                target_iid = iid

        children = self.tree.get_children()
        # Fallback: if still nothing targeted, pick first child
        if not target_iid and children:
            target_iid = children[0]

        if target_iid:
            self.tree.selection_set(target_iid)
            self.tree.focus(target_iid)
            if select_name or not prev_focus:
                # Scroll into view when focus changed intentionally
                self.tree.see(target_iid)
            else:
                # Restore approximate scroll position
                try:
                    self.tree.yview_moveto(scroll_top)
                except Exception:
                    self.tree.see(target_iid)

        self.update_status(len(dirs), len(files), sum(f["size"] for f in files))

    def update_status(self, num_dirs=None, num_files=None, total_size=None):
        if self.marked_items:
            selected = list(self.marked_items)
        else:
            selected = [s for s in self.tree.selection() if s != ".."]
        sel_size = 0
        arch_info = find_archive_root(self.current_path)
        for name in selected:
            p = self.current_path / name
            try:
                if arch_info:
                    entries = list_archive_entries(arch_info[0], arch_info[1])
                    for e in entries:
                        if e["name"] == name and not e["is_dir"]:
                            sel_size += e["size"]
                            break
                elif p.is_file():
                    sel_size += p.stat().st_size
            except OSError:
                pass

        try:
            drive_path = arch_info[0] if arch_info else self.current_path
            usage = shutil.disk_usage(drive_path)
            free_str = f"Free: {format_size(usage.free)}"
        except OSError:
            free_str = ""

        arch_label = f"Archive: {arch_info[0].name} | " if arch_info else ""
        mark_label = "Marked" if self.marked_items else "Selected"
        self.status_var.set(
            f"{arch_label}{mark_label}: {len(selected)} item(s) ({format_size(sel_size)})   |   {free_str}"
        )

    def get_selected_paths(self) -> list[Path]:
        """Return list of marked/selected Paths (excluding '..'). Falls back to focused item."""
        if self.marked_items:
            ordered = [
                iid for iid in self.tree.get_children() if iid in self.marked_items and iid != ".."
            ]
            return [self.current_path / name for name in ordered]
        sel = [s for s in self.tree.selection() if s != ".."]
        if not sel:
            f = self.tree.focus()
            if f and f != "..":
                sel = [f]
        return [self.current_path / name for name in sel]

    def get_focused_path(self) -> Path | None:
        f = self.tree.focus()
        if not f or f == "..":
            return None
        return self.current_path / f

    def _on_activate_item(self, event=None):
        focus_id = self.tree.focus()
        if not focus_id:
            return
        if focus_id == "..":
            self.go_up()
            return

        target = self.current_path / focus_id
        if self.is_dir(target) or is_archive_file(target):
            self.navigate_to(target)
        else:
            arch_info = find_archive_root(target)
            if arch_info:
                self.app.action_view()
            else:
                self.open_with_os(target)

    @staticmethod
    def open_with_os(path: Path):
        try:
            if os.name == "nt":
                os.startfile(str(path))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as e:
            messagebox.showerror("Open Error", f"Could not open file:\n{e}")


class FileCompareWindow(tk.Toplevel):
    """Side-by-side line-by-line text file comparison tool (Compare by Content)."""

    def __init__(self, parent, file1: Path | None = None, file2: Path | None = None):
        super().__init__(parent)
        self.parent_app = parent
        self.file1_path = file1
        self.file2_path = file2

        self.diff_blocks: list[tuple[int, int]] = []
        self.current_diff_idx: int = -1
        self.total_rows: int = 0

        self.title("Compare by Content - PyCommander")
        self.geometry("1100x680")
        self.minsize(800, 480)

        self._build_ui()
        if self.file1_path and self.file2_path:
            self.compare_files()

    def _build_ui(self):
        # Top Path Selection and Options frame
        top_frame = ttk.Frame(self, padding=6)
        top_frame.pack(fill=tk.X)

        # File 1 row
        f1_row = ttk.Frame(top_frame)
        f1_row.pack(fill=tk.X, pady=1)
        ttk.Label(f1_row, text="File 1:", width=8, anchor=tk.W).pack(side=tk.LEFT)
        self.f1_var = tk.StringVar(value=str(self.file1_path) if self.file1_path else "")
        self.f1_entry = ttk.Entry(f1_row, textvariable=self.f1_var)
        self.f1_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        self.f1_entry.bind("<Return>", lambda e: self.compare_files())
        ttk.Button(f1_row, text="Browse...", width=9, command=lambda: self._browse_file(1)).pack(side=tk.LEFT)

        # File 2 row
        f2_row = ttk.Frame(top_frame)
        f2_row.pack(fill=tk.X, pady=1)
        ttk.Label(f2_row, text="File 2:", width=8, anchor=tk.W).pack(side=tk.LEFT)
        self.f2_var = tk.StringVar(value=str(self.file2_path) if self.file2_path else "")
        self.f2_entry = ttk.Entry(f2_row, textvariable=self.f2_var)
        self.f2_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        self.f2_entry.bind("<Return>", lambda e: self.compare_files())
        ttk.Button(f2_row, text="Browse...", width=9, command=lambda: self._browse_file(2)).pack(side=tk.LEFT)

        # Toolbar row
        tb_row = ttk.Frame(top_frame)
        tb_row.pack(fill=tk.X, pady=(4, 0))

        ttk.Button(tb_row, text="↓ Next Diff (F7)", command=self.next_diff).pack(side=tk.LEFT, padx=(0, 3))
        ttk.Button(tb_row, text="↑ Prev Diff (Shift+F7)", command=self.prev_diff).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(tb_row, text="⟳ Re-compare", command=self.compare_files).pack(side=tk.LEFT, padx=(0, 10))

        self.ignore_ws_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(tb_row, text="Ignore Whitespace", variable=self.ignore_ws_var, command=self.compare_files).pack(side=tk.LEFT, padx=(0, 6))

        self.ignore_case_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(tb_row, text="Ignore Case", variable=self.ignore_case_var, command=self.compare_files).pack(side=tk.LEFT, padx=(0, 12))

        self.status_lbl = ttk.Label(tb_row, text="", font=("Segoe UI", 9, "bold"))
        self.status_lbl.pack(side=tk.LEFT)

        # Paned Window for side-by-side text views
        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))

        # Left side
        left_frame = ttk.Frame(paned)
        paned.add(left_frame, weight=1)
        self.left_hdr = ttk.Label(left_frame, text="File 1", font=("Segoe UI", 9, "bold"), relief=tk.RIDGE, padding=2)
        self.left_hdr.pack(fill=tk.X)
        l_text_frame = ttk.Frame(left_frame)
        l_text_frame.pack(fill=tk.BOTH, expand=True)
        self.text1 = tk.Text(l_text_frame, wrap=tk.NONE, font=("Consolas", 10), state=tk.DISABLED, bd=1, relief=tk.SOLID)
        self.text1.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        hsb1 = ttk.Scrollbar(left_frame, orient=tk.HORIZONTAL, command=self.text1.xview)
        hsb1.pack(fill=tk.X)
        self.text1.configure(xscrollcommand=hsb1.set)

        # Right side
        right_frame = ttk.Frame(paned)
        paned.add(right_frame, weight=1)
        self.right_hdr = ttk.Label(right_frame, text="File 2", font=("Segoe UI", 9, "bold"), relief=tk.RIDGE, padding=2)
        self.right_hdr.pack(fill=tk.X)
        r_text_frame = ttk.Frame(right_frame)
        r_text_frame.pack(fill=tk.BOTH, expand=True)
        self.text2 = tk.Text(r_text_frame, wrap=tk.NONE, font=("Consolas", 10), state=tk.DISABLED, bd=1, relief=tk.SOLID)
        self.text2.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        hsb2 = ttk.Scrollbar(right_frame, orient=tk.HORIZONTAL, command=self.text2.xview)
        hsb2.pack(fill=tk.X)
        self.text2.configure(xscrollcommand=hsb2.set)

        # Shared vertical scrollbar
        self.vsb = ttk.Scrollbar(r_text_frame, orient=tk.VERTICAL, command=self._sync_yview)
        self.vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # Configure Text tags
        for t in (self.text1, self.text2):
            t.tag_configure("line_num", foreground="#777777", background="#f0f0f0")
            t.tag_configure("diff_replace", background="#ffdddd", foreground="#8a0000")
            t.tag_configure("diff_delete", background="#ffe6cc", foreground="#804000")
            t.tag_configure("diff_insert", background="#e6ffed", foreground="#006622")
            t.tag_configure("diff_blank", background="#f3f3f3", foreground="#aaaaaa")
            t.tag_configure("diff_focus", background="#fff3cd", font=("Consolas", 10, "bold"))
            t.bind("<MouseWheel>", self._on_mousewheel)
            t.bind("<Button-4>", self._on_mousewheel)
            t.bind("<Button-5>", self._on_mousewheel)

        self.text1.configure(yscrollcommand=self._on_t1_scroll)
        self.text2.configure(yscrollcommand=self._on_t2_scroll)

        # Keyboard shortcuts
        self.bind("<F7>", lambda e: self.next_diff())
        self.bind("<Shift-F7>", lambda e: self.prev_diff())
        self.bind("<Down>", lambda e: self.next_diff())
        self.bind("<Up>", lambda e: self.prev_diff())
        self.bind("<Escape>", lambda e: self.destroy())

    def _sync_yview(self, *args):
        self.text1.yview(*args)
        self.text2.yview(*args)

    def _on_t1_scroll(self, *args):
        self.vsb.set(*args)
        self.text2.yview_moveto(args[0])

    def _on_t2_scroll(self, *args):
        self.vsb.set(*args)
        self.text1.yview_moveto(args[0])

    def _on_mousewheel(self, event):
        delta = int(-1 * (event.delta / 120)) if os.name == "nt" else (1 if event.num == 5 else -1)
        self.text1.yview_scroll(delta, "units")
        self.text2.yview_scroll(delta, "units")
        return "break"

    def _browse_file(self, target_idx: int):
        init_dir = str(self.parent_app.active_pane.current_path)
        path = filedialog.askopenfilename(parent=self, initialdir=init_dir, title=f"Select File {target_idx}")
        if path:
            if target_idx == 1:
                self.f1_var.set(path)
            else:
                self.f2_var.set(path)
            self.compare_files()

    def compare_files(self):
        f1_str = self.f1_var.get().strip()
        f2_str = self.f2_var.get().strip()
        if not f1_str or not f2_str:
            return

        p1 = Path(f1_str)
        p2 = Path(f2_str)

        try:
            content1 = get_file_text(p1)
        except Exception as e:
            messagebox.showerror("Error Reading File 1", f"Cannot read '{p1}':\n{e}", parent=self)
            return

        try:
            content2 = get_file_text(p2)
        except Exception as e:
            messagebox.showerror("Error Reading File 2", f"Cannot read '{p2}':\n{e}", parent=self)
            return

        self.left_hdr.configure(text=f"File 1: {p1.name} ({format_size(len(content1.encode('utf-8')))})")
        self.right_hdr.configure(text=f"File 2: {p2.name} ({format_size(len(content2.encode('utf-8')))})")

        lines1 = content1.splitlines()
        lines2 = content2.splitlines()

        ignore_ws = self.ignore_ws_var.get()
        ignore_case = self.ignore_case_var.get()

        def norm(l: str) -> str:
            if ignore_ws:
                l = l.strip()
            if ignore_case:
                l = l.lower()
            return l

        t1_norm = [norm(l) for l in lines1]
        t2_norm = [norm(l) for l in lines2]

        matcher = difflib.SequenceMatcher(None, t1_norm, t2_norm)
        rows = []
        self.diff_blocks = []

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            start_row = len(rows)
            if tag == "equal":
                for k in range(i2 - i1):
                    rows.append((i1 + k + 1, lines1[i1 + k], j1 + k + 1, lines2[j1 + k], "equal"))
            elif tag == "replace":
                c1, c2 = i2 - i1, j2 - j1
                max_c = max(c1, c2)
                for k in range(max_c):
                    n1 = i1 + k + 1 if k < c1 else ""
                    l1 = lines1[i1 + k] if k < c1 else ""
                    n2 = j1 + k + 1 if k < c2 else ""
                    l2 = lines2[j1 + k] if k < c2 else ""
                    rows.append((n1, l1, n2, l2, "replace"))
                self.diff_blocks.append((start_row, len(rows) - 1))
            elif tag == "delete":
                for k in range(i2 - i1):
                    rows.append((i1 + k + 1, lines1[i1 + k], "", "", "delete"))
                self.diff_blocks.append((start_row, len(rows) - 1))
            elif tag == "insert":
                for k in range(j2 - j1):
                    rows.append(("", "", j1 + k + 1, lines2[j1 + k], "insert"))
                self.diff_blocks.append((start_row, len(rows) - 1))

        self.total_rows = len(rows)
        self.current_diff_idx = -1

        # Populate text widgets
        self.text1.configure(state=tk.NORMAL)
        self.text2.configure(state=tk.NORMAL)
        self.text1.delete("1.0", tk.END)
        self.text2.delete("1.0", tk.END)

        num_width = max(4, len(str(self.total_rows)))

        for r_idx, (n1, l1, n2, l2, tag) in enumerate(rows):
            n1_str = f"{n1:>{num_width}} | " if n1 != "" else f"{'':>{num_width}} | "
            n2_str = f"{n2:>{num_width}} | " if n2 != "" else f"{'':>{num_width}} | "

            self.text1.insert(tk.END, n1_str, ("line_num",))
            self.text2.insert(tk.END, n2_str, ("line_num",))

            if tag == "equal":
                self.text1.insert(tk.END, l1 + "\n")
                self.text2.insert(tk.END, l2 + "\n")
            elif tag == "replace":
                tag1 = "diff_replace" if n1 != "" else "diff_blank"
                tag2 = "diff_replace" if n2 != "" else "diff_blank"
                val1 = l1 if n1 != "" else "~~~"
                val2 = l2 if n2 != "" else "~~~"
                self.text1.insert(tk.END, val1 + "\n", (tag1, f"row_{r_idx}"))
                self.text2.insert(tk.END, val2 + "\n", (tag2, f"row_{r_idx}"))
            elif tag == "delete":
                self.text1.insert(tk.END, l1 + "\n", ("diff_delete", f"row_{r_idx}"))
                self.text2.insert(tk.END, "~~~\n", ("diff_blank", f"row_{r_idx}"))
            elif tag == "insert":
                self.text1.insert(tk.END, "~~~\n", ("diff_blank", f"row_{r_idx}"))
                self.text2.insert(tk.END, l2 + "\n", ("diff_insert", f"row_{r_idx}"))

        self.text1.configure(state=tk.DISABLED)
        self.text2.configure(state=tk.DISABLED)

        # Update status
        if not self.diff_blocks:
            self.status_lbl.configure(text="✓ Files are identical!", foreground="#007700")
        else:
            diff_lines = sum(end - start + 1 for start, end in self.diff_blocks)
            self.status_lbl.configure(
                text=f"⚠ {len(self.diff_blocks)} difference block(s) ({diff_lines} lines)",
                foreground="#b71c1c",
            )
            self.next_diff()

    def next_diff(self):
        if not self.diff_blocks:
            return
        self.current_diff_idx = (self.current_diff_idx + 1) % len(self.diff_blocks)
        self._highlight_diff_block()

    def prev_diff(self):
        if not self.diff_blocks:
            return
        self.current_diff_idx = (self.current_diff_idx - 1) % len(self.diff_blocks)
        self._highlight_diff_block()

    def _highlight_diff_block(self):
        start_row, end_row = self.diff_blocks[self.current_diff_idx]
        self.status_lbl.configure(
            text=f"Difference {self.current_diff_idx + 1} of {len(self.diff_blocks)} (Line {start_row + 1})",
            foreground="#b71c1c",
        )
        pos = max(0.0, (start_row - 2) / max(1, self.total_rows))
        self.text1.yview_moveto(pos)
        self.text2.yview_moveto(pos)

        self.text1.tag_remove("diff_focus", "1.0", tk.END)
        self.text2.tag_remove("diff_focus", "1.0", tk.END)
        for r in range(start_row, end_row + 1):
            self.text1.tag_add("diff_focus", f"{r + 1}.0", f"{r + 1}.end")
            self.text2.tag_add("diff_focus", f"{r + 1}.0", f"{r + 1}.end")


class TotalCommanderApp(tk.Tk):
    """Main application window housing dual panes, function key bar, and command line."""

    def __init__(self):
        super().__init__()
        self.title("PyCommander - Dual Pane File Manager")
        self.geometry("1150x700")
        self.minsize(800, 480)

        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Treeview", rowheight=22)

        self.cmd_history: list[str] = []
        self.cmd_history_idx: int | None = None
        self.cmd_draft: str = ""

        self._build_menu()
        self._build_layout()
        self._bind_shortcuts()

        self.active_pane: FilePane = self.left_pane
        self.set_active_pane(self.left_pane)
        self.left_pane.tree.focus_set()

    def _build_menu(self):
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Rename (F2)", command=self.action_rename)
        file_menu.add_command(label="View (F3)", command=self.action_view)
        file_menu.add_command(label="Edit (F4)", command=self.action_edit)
        file_menu.add_command(label="Copy (F5)", command=self.action_copy)
        file_menu.add_command(label="Rename / Move (F6)", command=self.action_move)
        file_menu.add_command(label="New Folder (F7)", command=self.action_mkdir)
        file_menu.add_command(label="Delete (F8 / Del)", command=self.action_delete)
        file_menu.add_separator()
        file_menu.add_command(label="Compare by Content... (Ctrl+Alt+C)", command=self.action_compare)
        file_menu.add_separator()
        file_menu.add_command(label="Properties (Alt+Enter)", command=self.action_properties)
        file_menu.add_separator()
        file_menu.add_command(label="Exit (F10)", command=self.quit)
        menubar.add_cascade(label="Files", menu=file_menu)

        mark_menu = tk.Menu(menubar, tearoff=0)
        mark_menu.add_command(
            label="Toggle Mark & Move Down (Insert)",
            command=lambda: self.active_pane._on_insert_key(None),
        )
        mark_menu.add_command(
            label="Toggle Mark (Space)",
            command=lambda: self.active_pane._on_space_key(None),
        )
        mark_menu.add_separator()
        mark_menu.add_command(label="Select All (Ctrl+A)", command=self.action_select_all)
        mark_menu.add_command(label="Unselect All (Ctrl+D)", command=self.action_unselect_all)
        mark_menu.add_command(label="Invert Selection (*)", command=self.action_invert_selection)
        menubar.add_cascade(label="Mark", menu=mark_menu)

        nav_menu = tk.Menu(menubar, tearoff=0)
        nav_menu.add_command(label="Switch Pane (Tab)", command=self.switch_pane)
        nav_menu.add_command(label="Parent Directory (Backspace)", command=lambda: self.active_pane.go_up())
        nav_menu.add_command(label="History: Back (Alt+Left)", command=lambda: self.active_pane.history_back())
        nav_menu.add_command(label="History: Forward (Alt+Right)", command=lambda: self.active_pane.history_forward())
        nav_menu.add_command(label="History: Path List (Alt+Down)", command=lambda: self.active_pane.show_history_menu())
        nav_menu.add_command(label="Sync Inactive Pane (=)", command=self.action_sync_panes)
        nav_menu.add_command(label="Refresh Both Panes (Ctrl+R)", command=self.refresh_both)
        nav_menu.add_separator()
        nav_menu.add_command(label="Open Terminal Here (F9)", command=self.action_open_terminal)
        menubar.add_cascade(label="Navigate", menu=nav_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="All Actions & Keyboard Shortcuts (F1)", command=self.action_help)
        help_menu.add_separator()
        help_menu.add_command(label="About PyCommander", command=self.action_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.config(menu=menubar)

    def _build_layout(self):
        # Dual PanedWindow
        self.paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True, padx=4, pady=(4, 2))

        start_left = Path(__file__).resolve().parent
        start_right = Path.home()

        self.left_pane = FilePane(self.paned, self, start_left)
        self.right_pane = FilePane(self.paned, self, start_right)

        self.paned.add(self.left_pane, weight=1)
        self.paned.add(self.right_pane, weight=1)

        # Quick shell command bar
        cmd_frame = ttk.Frame(self, padding=(4, 2))
        cmd_frame.pack(fill=tk.X)

        self.cmd_prompt_var = tk.StringVar(value=f"{start_left}>")
        ttk.Label(cmd_frame, textvariable=self.cmd_prompt_var, font=("Consolas", 9)).pack(
            side=tk.LEFT, padx=(0, 4)
        )
        self.cmd_var = tk.StringVar()
        self.cmd_entry = ttk.Combobox(
            cmd_frame, textvariable=self.cmd_var, font=("Consolas", 10)
        )
        self.cmd_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
        self.cmd_entry.bind("<Return>", self._run_shell_command)
        self.cmd_entry.bind("<<ComboboxSelected>>", self._on_cmd_combo_selected)
        self.cmd_entry.bind("<Up>", self._on_cmd_up)
        self.cmd_entry.bind("<Down>", self._on_cmd_down)

        run_btn = ttk.Button(cmd_frame, text="⏎ Run", width=6, command=self._run_shell_command)
        run_btn.pack(side=tk.LEFT, padx=(0, 2))

        hist_cmd_btn = ttk.Button(cmd_frame, text="History ▾", command=self._show_cmd_history_menu)
        hist_cmd_btn.pack(side=tk.LEFT)

        # Bottom Function Key Bar (F3 - F10)
        fn_bar = ttk.Frame(self, padding=4)
        fn_bar.pack(fill=tk.X, side=tk.BOTTOM)

        buttons = [
            ("F1 Help", self.action_help),
            ("F2 Rename", self.action_rename),
            ("F3 View", self.action_view),
            ("F4 Edit", self.action_edit),
            ("F5 Copy", self.action_copy),
            ("F6 Move", self.action_move),
            ("F7 MkDir", self.action_mkdir),
            ("F8 Delete", self.action_delete),
            ("F9 Term", self.action_open_terminal),
            ("F10 Quit", self.quit),
        ]
        for idx, (label, cmd) in enumerate(buttons):
            btn = ttk.Button(fn_bar, text=label, command=cmd)
            btn.grid(row=0, column=idx, sticky="ew", padx=2)
            fn_bar.columnconfigure(idx, weight=1)

    def _bind_shortcuts(self):
        self.bind("<F1>", lambda e: self.action_help())
        self.bind("<F2>", lambda e: self.action_rename())
        self.bind("<F3>", lambda e: self.action_view())
        self.bind("<F4>", lambda e: self.action_edit())
        self.bind("<F5>", lambda e: self.action_copy())
        self.bind("<F6>", lambda e: self.action_move())
        self.bind("<F7>", lambda e: self.action_mkdir())
        self.bind("<F8>", lambda e: self.action_delete())
        self.bind("<Delete>", lambda e: self.action_delete())
        self.bind("<F9>", lambda e: self.action_open_terminal())
        self.bind("<F10>", lambda e: self.quit())
        self.bind("<Control-r>", lambda e: self.refresh_both())
        self.bind("<Control-a>", lambda e: self.action_select_all())
        self.bind("<Control-d>", lambda e: self.action_unselect_all())
        self.bind("<KP_Multiply>", lambda e: self.action_invert_selection())
        self.bind("<asterisk>", lambda e: self.action_invert_selection())
        self.bind("<equal>", lambda e: self.action_sync_panes())
        self.bind("<Alt-Return>", lambda e: self.action_properties())
        self.bind("<Control-Alt-c>", lambda e: self.action_compare())
        self.bind("<Control-Alt-C>", lambda e: self.action_compare())
        self.bind("<Alt-Left>", lambda e: self.active_pane.history_back())
        self.bind("<Alt-Right>", lambda e: self.active_pane.history_forward())
        self.bind("<Alt-Down>", lambda e: self.active_pane.show_history_menu())

    def set_active_pane(self, pane: FilePane):
        self.active_pane = pane
        self.left_pane.set_active_visual(pane is self.left_pane)
        self.right_pane.set_active_visual(pane is self.right_pane)
        self.cmd_prompt_var.set(f"{pane.current_path}>")

    @property
    def inactive_pane(self) -> FilePane:
        return self.right_pane if self.active_pane is self.left_pane else self.left_pane

    def switch_pane(self):
        target = self.inactive_pane
        self.set_active_pane(target)
        target.tree.focus_set()

    def refresh_both(self):
        self.left_pane.refresh(preserve_focus=True)
        self.right_pane.refresh(preserve_focus=True)
        self.cmd_prompt_var.set(f"{self.active_pane.current_path}>")

    def action_sync_panes(self):
        self.inactive_pane.navigate_to(self.active_pane.current_path)

    def action_select_all(self):
        pane = self.active_pane
        items = [i for i in pane.tree.get_children() if i != ".."]
        pane.marked_items = set(items)
        for iid in items:
            pane._update_item_visual(iid)
        pane.update_status()

    def action_unselect_all(self):
        pane = self.active_pane
        old_marked = list(pane.marked_items)
        pane.marked_items.clear()
        for iid in old_marked:
            pane._update_item_visual(iid)
        pane.update_status()

    def action_invert_selection(self):
        pane = self.active_pane
        all_items = [i for i in pane.tree.get_children() if i != ".."]
        pane.marked_items = {i for i in all_items if i not in pane.marked_items}
        for iid in all_items:
            pane._update_item_visual(iid)
        pane.update_status()

    def action_open_terminal(self, shell_cmd: str | None = None):
        """F9: Open an external interactive terminal window in the active pane's folder."""
        cwd = str(self.active_pane.current_path)
        try:
            if os.name == "nt":
                exe = shell_cmd or "cmd.exe"
                subprocess.Popen(
                    exe,
                    cwd=cwd,
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                )
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-a", "Terminal", cwd])
            else:
                for term in ("x-terminal-emulator", "gnome-terminal", "konsole", "xfce4-terminal", "xterm"):
                    if shutil.which(term):
                        subprocess.Popen([term], cwd=cwd)
                        break
        except Exception as e:
            messagebox.showerror("Terminal Error", f"Could not open terminal:\n{e}")

    def _on_cmd_combo_selected(self, event=None):
        self.cmd_history_idx = None
        self.cmd_draft = ""
        self.cmd_entry.focus_set()
        self.cmd_entry.icursor(tk.END)

    def _on_cmd_up(self, event):
        if not self.cmd_history:
            return "break"
        if self.cmd_history_idx is None:
            self.cmd_draft = self.cmd_var.get()
            self.cmd_history_idx = len(self.cmd_history) - 1
        elif self.cmd_history_idx > 0:
            self.cmd_history_idx -= 1
        self.cmd_var.set(self.cmd_history[self.cmd_history_idx])
        self.cmd_entry.icursor(tk.END)
        return "break"

    def _on_cmd_down(self, event):
        if self.cmd_history_idx is not None:
            if self.cmd_history_idx < len(self.cmd_history) - 1:
                self.cmd_history_idx += 1
                self.cmd_var.set(self.cmd_history[self.cmd_history_idx])
            else:
                self.cmd_history_idx = None
                self.cmd_var.set(self.cmd_draft)
            self.cmd_entry.icursor(tk.END)
        return "break"

    def _show_cmd_history_menu(self, event=None):
        if not self.cmd_history:
            messagebox.showinfo("Command History", "No commands in history yet.", parent=self)
            return
        menu = tk.Menu(self, tearoff=0)
        for c in reversed(self.cmd_history[-20:]):
            disp = c if len(c) <= 60 else c[:57] + "..."
            menu.add_command(
                label=f"▶ {disp}",
                command=lambda cmd_str=c: self._execute_from_history(cmd_str),
            )
        menu.add_separator()
        menu.add_command(label="Clear Command History", command=self._clear_cmd_history)

        x = self.cmd_entry.winfo_rootx()
        y = self.cmd_entry.winfo_rooty()
        menu.tk_popup(x, y)

    def _execute_from_history(self, cmd_str: str):
        self.cmd_var.set(cmd_str)
        self._run_shell_command()

    def _clear_cmd_history(self):
        self.cmd_history.clear()
        self.cmd_entry["values"] = []
        self.cmd_history_idx = None
        self.cmd_draft = ""

    def _run_shell_command(self, event=None):
        cmd = self.cmd_var.get().strip()
        if not cmd:
            return
        self.cmd_var.set("")

        # Save to command history
        if cmd in self.cmd_history:
            self.cmd_history.remove(cmd)
        self.cmd_history.append(cmd)
        if len(self.cmd_history) > 50:
            self.cmd_history.pop(0)
        self.cmd_entry["values"] = list(reversed(self.cmd_history))
        self.cmd_history_idx = None
        self.cmd_draft = ""

        cwd_path = self.active_pane.current_path
        cwd = str(cwd_path)

        parts = cmd.split(maxsplit=1)
        first_token = parts[0].lower()

        # Built-in directory change support: "cd <dir>"
        if first_token == "cd":
            target_str = parts[1].strip('"\'') if len(parts) > 1 else str(Path.home())
            target = (cwd_path / os.path.expandvars(os.path.expanduser(target_str))).resolve()
            if target.is_dir():
                self.active_pane.navigate_to(target)
            else:
                messagebox.showerror("cd Error", f"Directory not found:\n{target}")
            self.active_pane.tree.focus_set()
            return

        # Interactive console shells: open in a new console window so the GUI never hangs
        interactive_shells = {"cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe", "wt", "wt.exe", "bash", "sh", "zsh"}
        if first_token in interactive_shells and len(parts) == 1:
            self.action_open_terminal(shell_cmd=cmd)
            self.active_pane.tree.focus_set()
            return

        # Run non-interactive commands on a background thread with stdin=DEVNULL so GUI never freezes
        def worker():
            try:
                res = subprocess.run(
                    cmd,
                    shell=True,
                    cwd=cwd,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                output = (res.stdout or "") + (res.stderr or "")
                self.after(0, lambda: self._on_command_finished(cmd, output, None))
            except Exception as e:
                self.after(0, lambda err=e: self._on_command_finished(cmd, "", err))

        threading.Thread(target=worker, daemon=True).start()
        self.active_pane.tree.focus_set()

    def _on_command_finished(self, cmd: str, output: str, error: Exception | None):
        if error:
            messagebox.showerror("Command Error", str(error))
        elif output.strip():
            self._show_text_window(f"Command Output: {cmd}", output, editable=False)
        self.refresh_both()

    # --- File Operations ---

    def action_rename(self):
        path = self.active_pane.get_focused_path()
        if not path:
            return
        new_name = simpledialog.askstring(
            "Rename", f"Rename '{path.name}' to:", initialvalue=path.name, parent=self
        )
        if not new_name or new_name == path.name:
            return
        try:
            target = path.parent / new_name
            path.rename(target)
            self.active_pane.refresh(select_name=new_name)
            if self.inactive_pane.current_path == self.active_pane.current_path:
                self.inactive_pane.refresh()
        except Exception as e:
            messagebox.showerror("Rename Error", str(e))

    def action_view(self):
        """F3: Built-in quick file viewer (text + hex fallback for binary)."""
        path = self.active_pane.get_focused_path()
        if not path:
            return
        if self.active_pane.is_dir(path):
            arch_info = find_archive_root(path)
            if arch_info:
                arch_path, relpath = arch_info
                entries = list_archive_entries(arch_path, relpath)
                total_size = sum(e["size"] for e in entries if not e["is_dir"])
                file_count = sum(1 for e in entries if not e["is_dir"])
                dir_count = sum(1 for e in entries if e["is_dir"])
                messagebox.showinfo(
                    "Archive Folder Info",
                    f"Archive: {arch_path.name}\n"
                    f"Folder: {path.name}\n\n"
                    f"Subfolders: {dir_count}\n"
                    f"Files: {file_count}\n"
                    f"Total Size: {format_size(total_size)} ({total_size:,} bytes)",
                )
            else:
                total_size = 0
                file_count = 0
                dir_count = 0
                for root, dirs, files in os.walk(path):
                    dir_count += len(dirs)
                    file_count += len(files)
                    for f in files:
                        try:
                            total_size += (Path(root) / f).stat().st_size
                        except OSError:
                            pass
                messagebox.showinfo(
                    "Directory Info",
                    f"Folder: {path.name}\n\n"
                    f"Subfolders: {dir_count}\n"
                    f"Files: {file_count}\n"
                    f"Total Size: {format_size(total_size)} ({total_size:,} bytes)",
                )
            return

        try:
            raw = get_file_bytes(path)[: 256 * 1024]  # Preview up to 256 KB
            try:
                content = raw.decode("utf-8")
            except UnicodeDecodeError:
                # Format as Hex Dump for binary files
                lines = []
                for offset in range(0, min(len(raw), 16384), 16):
                    chunk = raw[offset : offset + 16]
                    hex_part = " ".join(f"{b:02X}" for b in chunk)
                    ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
                    lines.append(f"{offset:08X}  {hex_part:<47}  {ascii_part}")
                content = "[Binary File - Hex Preview (First 16 KB)]\n\n" + "\n".join(lines)
            self._show_text_window(f"Lister (F3) - {path.name}", content, editable=False)
        except Exception as e:
            messagebox.showerror("View Error", f"Cannot read file:\n{e}")

    def action_edit(self):
        """F4: Built-in text editor for modifying text files."""
        path = self.active_pane.get_focused_path()
        if not path or self.active_pane.is_dir(path):
            return
        if find_archive_root(path):
            messagebox.showinfo(
                "Archive File",
                "Editing files directly inside archives is not supported. Use F3 to view or F5 to extract.",
                parent=self,
            )
            return
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            messagebox.showwarning("Binary File", "Cannot edit binary file in text editor.")
            return
        except Exception as e:
            messagebox.showerror("Edit Error", f"Cannot open file:\n{e}")
            return

        self._show_text_window(f"Editor (F4) - {path}", content, editable=True, save_path=path)

    def _show_text_window(
        self, title: str, content: str, editable: bool = False, save_path: Path | None = None
    ):
        win = tk.Toplevel(self)
        win.title(title)
        win.geometry("800x580")

        if editable and save_path:
            toolbar = ttk.Frame(win, padding=4)
            toolbar.pack(fill=tk.X)

            def save_file():
                try:
                    new_text = text_widget.get("1.0", "end-1c")
                    save_path.write_text(new_text, encoding="utf-8")
                    self.refresh_both()
                    win.destroy()
                except Exception as e:
                    messagebox.showerror("Save Error", str(e), parent=win)

            ttk.Button(toolbar, text="💾 Save & Close (Ctrl+S)", command=save_file).pack(
                side=tk.LEFT, padx=2
            )
            win.bind("<Control-s>", lambda e: save_file())

        frame = ttk.Frame(win)
        frame.pack(fill=tk.BOTH, expand=True)

        text_widget = tk.Text(frame, wrap=tk.NONE, font=("Consolas", 10), undo=editable)
        vsb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text_widget.yview)
        hsb = ttk.Scrollbar(win, orient=tk.HORIZONTAL, command=text_widget.xview)
        text_widget.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb.pack(fill=tk.X)

        text_widget.insert("1.0", content)
        if not editable:
            text_widget.configure(state=tk.DISABLED)

        win.bind("<Escape>", lambda e: win.destroy())
        text_widget.focus_set()

    def action_copy(self):
        """F5: Copy selected files/folders from active pane to inactive pane (extracts from archives)."""
        sources = self.active_pane.get_selected_paths()
        if not sources:
            return
        dest_dir = self.inactive_pane.current_path

        if find_archive_root(dest_dir):
            messagebox.showwarning(
                "Archive Notice",
                "Writing files directly into an archive is not supported. Please copy into a normal directory.",
                parent=self,
            )
            return

        names = ", ".join(p.name for p in sources[:3])
        if len(sources) > 3:
            names += f" (+{len(sources) - 3} more)"

        dest_str = simpledialog.askstring(
            "Copy (F5)",
            f"Copy {len(sources)} item(s) ({names}) to:",
            initialvalue=str(dest_dir),
            parent=self,
        )
        if not dest_str:
            return
        target_dir = Path(dest_str)

        # Save cursor positions before operation
        active_focus = self.active_pane.tree.focus()
        inactive_focus = self.inactive_pane.tree.focus()
        active_scroll = self.active_pane.tree.yview()[0]
        inactive_scroll = self.inactive_pane.tree.yview()[0]

        resolver = ConflictResolver(self)
        errors = []
        for src in sources:
            if resolver.cancelled:
                break
            try:
                arch_info = find_archive_root(src)
                if arch_info:
                    ok = extract_archive_item(arch_info[0], arch_info[1], target_dir, resolver)
                    if not ok and resolver.cancelled:
                        break
                elif src.is_dir():
                    dst = target_dir / src.name
                    result = copy_dir_with_conflict(src, dst, resolver)
                    if result == "cancelled":
                        break
                else:
                    result = copy_file_with_conflict(src, target_dir, resolver)
                    if result == "cancelled":
                        break
            except Exception as e:
                errors.append(f"{src.name}: {e}")

        if errors:
            messagebox.showerror("Copy Errors", "\n".join(errors))

        # Clear marks on successfully copied items in active pane
        for src in sources:
            self.active_pane.marked_items.discard(src.name)

        # Refresh both panes while restoring positions
        # Active pane: keep the cursor on the same item (files were not removed)
        self.active_pane.refresh(
            select_name=active_focus if active_focus and active_focus != ".." else None,
            preserve_focus=True,
        )
        # Inactive pane: show newly arrived file; if single file copied, focus it; otherwise preserve
        if len(sources) == 1 and not resolver.cancelled:
            self.inactive_pane.refresh(select_name=sources[0].name)
        else:
            self.inactive_pane.refresh(preserve_focus=True)
        self.cmd_prompt_var.set(f"{self.active_pane.current_path}>")

    def action_move(self):
        """F6: Move or rename selected files/folders to the target directory."""
        sources = self.active_pane.get_selected_paths()
        if not sources:
            return
        dest_dir = self.inactive_pane.current_path

        default_val = (
            str(dest_dir / sources[0].name) if len(sources) == 1 else str(dest_dir)
        )
        dest_str = simpledialog.askstring(
            "Rename / Move (F6)",
            f"Move {len(sources)} item(s) to:",
            initialvalue=default_val,
            parent=self,
        )
        if not dest_str:
            return
        target_path = Path(dest_str)

        # Save cursor positions before operation
        active_focus = self.active_pane.tree.focus()
        # Find the item just before or after focused one, to land on after move
        all_children = list(self.active_pane.tree.get_children())
        try:
            focus_idx = all_children.index(active_focus)
        except ValueError:
            focus_idx = -1

        resolver = ConflictResolver(self)
        errors = []
        for src in sources:
            if resolver.cancelled:
                break
            try:
                if len(sources) == 1 and not target_path.is_dir():
                    dst = target_path
                else:
                    dst = target_path / src.name
                result = move_with_conflict(src, dst, resolver)
                if result == "cancelled":
                    break
            except Exception as e:
                errors.append(f"{src.name}: {e}")

        if errors:
            messagebox.showerror("Move Errors", "\n".join(errors))

        # Refresh active pane: land on the nearest surviving item
        # Find next surviving item from original position
        moved_names = {s.name for s in sources}
        survivors = [c for c in all_children if c not in moved_names]
        land_on = None
        if survivors:
            if focus_idx >= 0:
                # Find first survivor at or after the original position
                for c in all_children[focus_idx:]:
                    if c in survivors:
                        land_on = c
                        break
                if not land_on:
                    land_on = survivors[-1]

        self.active_pane.refresh(select_name=land_on, preserve_focus=(land_on is None))
        # Inactive pane: focus newly moved item when single item
        if len(sources) == 1 and not resolver.cancelled:
            self.inactive_pane.refresh(select_name=sources[0].name)
        else:
            self.inactive_pane.refresh(preserve_focus=True)
        self.cmd_prompt_var.set(f"{self.active_pane.current_path}>")

    def action_mkdir(self):
        """F7: Create a new directory in the active pane."""
        if find_archive_root(self.active_pane.current_path):
            messagebox.showinfo("Archive Notice", "Creating directories inside archives is not supported.", parent=self)
            return
        folder_name = simpledialog.askstring(
            "Create Directory (F7)", "Enter new folder name:", parent=self
        )
        if not folder_name:
            return
        new_dir = self.active_pane.current_path / folder_name
        try:
            new_dir.mkdir(parents=True, exist_ok=False)
            self.active_pane.refresh(select_name=new_dir.name)
            if self.inactive_pane.current_path == self.active_pane.current_path:
                self.inactive_pane.refresh()
        except Exception as e:
            messagebox.showerror("Create Folder Error", str(e))

    def action_delete(self):
        """F8 / Delete: Delete selected files/folders."""
        if find_archive_root(self.active_pane.current_path):
            messagebox.showinfo("Archive Notice", "Deleting items from archives is not supported.", parent=self)
            return
        sources = self.active_pane.get_selected_paths()
        if not sources:
            return

        listing = "\n".join(f"• {p.name}" for p in sources[:10])
        if len(sources) > 10:
            listing += f"\n... and {len(sources) - 10} more"

        confirm = messagebox.askyesno(
            "Confirm Delete (F8)",
            f"Permanently delete {len(sources)} selected item(s)?\n\n{listing}",
            icon=messagebox.WARNING,
            parent=self,
        )
        if not confirm:
            return

        errors = []
        for src in sources:
            try:
                if src.is_dir() and not src.is_symlink():
                    shutil.rmtree(src)
                else:
                    src.unlink()
            except Exception as e:
                errors.append(f"{src.name}: {e}")

        if errors:
            messagebox.showerror("Delete Errors", "\n".join(errors))
        self.refresh_both()

    def action_compare(self):
        """Compare selected text files line by line (Compare by Content)."""
        sources = self.active_pane.get_selected_paths()
        inactive_sources = self.inactive_pane.get_selected_paths()

        file1 = None
        file2 = None

        if len(sources) >= 2:
            file1 = sources[0]
            file2 = sources[1]
        elif len(sources) == 1:
            file1 = sources[0]
            if inactive_sources:
                file2 = inactive_sources[0]
            else:
                candidate = self.inactive_pane.current_path / file1.name
                if candidate.exists() or find_archive_root(candidate):
                    file2 = candidate
        else:
            f1 = self.active_pane.get_focused_path()
            f2 = self.inactive_pane.get_focused_path()
            if f1 and not self.active_pane.is_dir(f1):
                file1 = f1
            if f2 and not self.inactive_pane.is_dir(f2):
                file2 = f2

        FileCompareWindow(self, file1, file2)

    def action_properties(self):
        """Alt+Enter: Show detailed properties of focused item."""
        path = self.active_pane.get_focused_path()
        if not path:
            return
        arch_info = find_archive_root(path)
        if arch_info:
            arch_path, relpath = arch_info
            is_directory = self.active_pane.is_dir(path)
            size = 0
            mtime_str = "Unknown"
            if not is_directory:
                try:
                    entries = list_archive_entries(
                        arch_path,
                        str(Path(relpath).parent).replace("\\", "/").lstrip("."),
                    )
                    for e in entries:
                        if e["name"] == path.name:
                            size = e["size"]
                            if e["mtime"]:
                                mtime_str = datetime.datetime.fromtimestamp(
                                    e["mtime"]
                                ).strftime("%Y-%m-%d %H:%M:%S")
                            break
                except Exception:
                    pass
            kind = "Archive Folder" if is_directory else "Archive File Member"
            messagebox.showinfo(
                f"Properties - {path.name}",
                f"Name:      {path.name}\n"
                f"Type:      {kind}\n"
                f"Archive:   {arch_path}\n"
                f"Path:      {relpath or '/'}\n"
                f"Size:      {format_size(size)} ({size:,} bytes)\n"
                f"Modified:  {mtime_str}",
            )
            return

        try:
            st = path.stat()
            created = datetime.datetime.fromtimestamp(st.st_ctime).strftime("%Y-%m-%d %H:%M:%S")
            modified = datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            perms = stat.filemode(st.st_mode)
            kind = "Directory" if path.is_dir() else "File"
            messagebox.showinfo(
                f"Properties - {path.name}",
                f"Name:      {path.name}\n"
                f"Type:      {kind}\n"
                f"Location:  {path.parent}\n"
                f"Size:      {format_size(st.st_size)} ({st.st_size:,} bytes)\n"
                f"Created:   {created}\n"
                f"Modified:  {modified}\n"
                f"Mode:      {perms}",
            )
        except Exception as e:
            messagebox.showerror("Properties Error", str(e))

    def action_help(self):
        """F1: Display window with all available actions and keyboard shortcuts."""
        help_text = """========================================================================
                 PYCOMMANDER - ACTIONS & SHORTCUTS GUIDE
========================================================================

[ ARCHIVES AS FOLDERS ]
  Enter / Double-Click on any archive (.zip, .jar, .tar, .tgz, .tar.gz, etc.)
  to browse inside it just like a regular directory!
  - 📁 [..] or BackSpace: Navigate up inside the archive, or exit to the real folder
  - F3 Lister: View file contents directly inside archives
  - F5 Copy: Extract selected files/folders from archive into opposite panel
  - Alt+Enter: Inspect compressed member size, date, and archive details

[ COMPARE BY CONTENT ]
  Ctrl+Alt+C: Compare selected text files side-by-side line by line!
  - Compares 2 marked files, or active file with file in opposite panel
  - Color-coded highlights: red (changed/deleted), green (added), gray (pad)
  - Synchronized scrolling in lockstep
  - F7 / Down: Jump to next difference block
  - Shift+F7 / Up: Jump to previous difference block
  - Options: Ignore whitespace, Ignore case, Re-compare

[ FUNCTION KEYS ]
  F1              Show this Help window
  F2              Rename focused file or folder in place
  F3              Lister / View:
                    - Text files: built-in viewer
                    - Binary files: Hex + ASCII dump preview
                    - Folders / Archive folders: recursive size calculation
  F4              Editor: open text file in built-in editor (Ctrl+S to save)
  F5              Copy / Extract marked items from active to inactive pane
  F6              Move / Rename marked items to inactive pane
  F7              Create a new directory (MkDir) in the active pane
  F8 / Delete     Delete marked items (with confirmation prompt)
  F9              Open an external Terminal / Command Prompt in current folder
  F10             Quit PyCommander

[ NAVIGATION ]
  Tab             Switch active focus between Left and Right panes
  Up / Down       Move cursor bar up or down in the file list
  Enter           Open folder/archive or launch file with default OS application
  Double-Click    Open folder/archive or launch file with default OS application
  Backspace       Go up to parent directory or exit archive (..)
  Alt+Left / ◀    Go Back in path history
  Alt+Right / ▶   Go Forward in path history
  Alt+Down / ▾    Open Path History dropdown menu to jump to visited folders
  =               Synchronize inactive pane to active pane's folder
  Ctrl+R          Refresh both file panes
  Drive Dropdown  Switch drive / root mount point
  Path Bar        Type any path (supports ~ and env vars) and press Enter
  Column Headers  Click Name / Ext / Size / Modified to sort asc/desc

[ MARKING / SELECTION ]
  Insert          Toggle mark on current item (☑ red highlight) and move down
  Space           Toggle mark on current item without moving cursor
  Ctrl+A          Mark all items in the active pane
  Ctrl+D          Unmark / clear all marks in the active pane
  * (Multiply)    Invert marked items in the active pane
  Shift+Arrow     Extend cursor selection
  Ctrl+Click      Toggle multi-row cursor selection

[ COMMAND LINE & HISTORY ]
  Up / Down       Navigate previously run commands in the command prompt
  Combobox ▼      Click the dropdown arrow to view and select past commands
  History ▾       Open Command History popup menu to run or clear past commands
  ⏎ Run           Execute the command entered or selected in the command bar
  cd <folder>     Navigates active pane to <folder>
  cmd / powershell Spawns an external interactive console terminal
  Alt+Enter       Show file/folder properties (size, dates, permissions)
========================================================================"""
        self._show_text_window("Help - All Actions & Keyboard Shortcuts (F1)", help_text, editable=False)
        self._show_text_window("Help - All Actions & Keyboard Shortcuts (F1)", help_text, editable=False)

    def action_about(self):
        messagebox.showinfo(
            "About PyCommander",
            "PyCommander\n\n"
            "A dual-pane file manager inspired by Total Commander.\n"
            "Built with Python standard library (Tkinter, pathlib, shutil).",
            parent=self,
        )


if __name__ == "__main__":
    app = TotalCommanderApp()
    app.mainloop()
