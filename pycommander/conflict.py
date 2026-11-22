"""Overwrite confirmation UI and conflict resolver."""
import tkinter as tk
from tkinter import ttk
from pathlib import Path

from pycommander.utils import format_size, format_datetime
from pycommander.paths import get_path_info

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
