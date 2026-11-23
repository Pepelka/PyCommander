"""Reusable Tk dialogs for batch ops and tools."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox

from pycommander.multirename import preview_renames
from pycommander.search import search_files
from pycommander.compare_logic import diff_trees
from pycommander.duplicates import find_duplicates
from pathlib import Path


def center_toplevel_on_parent(win: tk.Toplevel, parent: tk.Misc) -> None:
    """Place a dialog over the parent window (not at screen 0,0)."""
    win.update_idletasks()
    try:
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        w = max(win.winfo_reqwidth(), win.winfo_width())
        h = max(win.winfo_reqheight(), win.winfo_height())
        if pw <= 1 or ph <= 1:
            parent.update_idletasks()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
        cx = max(0, px + (pw - w) // 2)
        cy = max(0, py + (ph - h) // 2)
        win.geometry(f"+{cx}+{cy}")
    except tk.TclError:
        pass


class OperationProgressDialog(tk.Toplevel):
    """Determinate progress bar with cancel for batch file operations."""

    def __init__(self, parent, title: str = "Working..."):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.resizable(False, False)
        self.cancelled = False
        self._on_cancel_cb = None
        frm = ttk.Frame(self, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)
        self.count_var = tk.StringVar(value="0 / 0")
        ttk.Label(frm, textvariable=self.count_var).pack(anchor=tk.W)
        self.detail_var = tk.StringVar(value="")
        ttk.Label(frm, textvariable=self.detail_var, wraplength=320).pack(anchor=tk.W, pady=(4, 6))
        self.pb = ttk.Progressbar(frm, mode="determinate", length=320)
        self.pb.pack(fill=tk.X, pady=(0, 8))
        ttk.Button(frm, text="Cancel", command=self._cancel).pack(anchor=tk.E)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        center_toplevel_on_parent(self, parent)
        self.grab_set()

    def set_on_cancel(self, callback):
        self._on_cancel_cb = callback

    def _cancel(self):
        self.cancelled = True
        if self._on_cancel_cb:
            self._on_cancel_cb()

    def set_detail(self, text: str):
        self.detail_var.set(text)
        self.update_idletasks()

    def update_progress(self, current: int, total: int, label: str = ""):
        extra = f" — {label}" if label else ""
        self.count_var.set(f"{current} / {total}{extra}")
        self.pb["maximum"] = max(1, total)
        self.pb["value"] = current
        if label:
            self.detail_var.set(label)
        self.update_idletasks()

    def close(self):
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()


def show_multirename_dialog(parent, names: list[str], on_apply):
    win = tk.Toplevel(parent)
    win.title("Multi-Rename")
    ttk.Label(win, text="Pattern ({name} {stem} {ext} {n})", padding=6).pack()
    pat = tk.StringVar(value="{stem}_{n:03d}{ext}")
    ttk.Entry(win, textvariable=pat, width=40).pack(padx=8)
    tv = ttk.Treeview(win, columns=("old", "new"), show="headings", height=8)
    tv.heading("old", text="From")
    tv.heading("new", text="To")
    tv.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

    def refresh_preview(*_):
        tv.delete(*tv.get_children())
        for old, new in preview_renames(names, pat.get()):
            tv.insert("", tk.END, values=(old, new))

    pat.trace_add("write", refresh_preview)
    refresh_preview()

    def apply():
        on_apply(pat.get())
        win.destroy()

    ttk.Button(win, text="Apply", command=apply).pack(pady=6)


def show_search_dialog(parent, root: Path, on_pick):
    win = tk.Toplevel(parent)
    win.title(f"Search in {root.name}")
    fq = tk.StringVar()
    cq = tk.StringVar()
    ttk.Entry(win, textvariable=fq, width=40).pack(padx=8, pady=4)
    ttk.Label(win, text="Filename contains").pack()
    ttk.Entry(win, textvariable=cq, width=40).pack(padx=8, pady=4)
    ttk.Label(win, text="Content contains (optional)").pack()
    lb = tk.Listbox(win, height=12, width=80)
    lb.pack(padx=8, pady=4, fill=tk.BOTH, expand=True)

    def run():
        lb.delete(0, tk.END)
        for p in search_files(root, name_contains=fq.get(), content_contains=cq.get()):
            lb.insert(tk.END, str(p))

    ttk.Button(win, text="Search", command=run).pack()
    lb.bind("<Double-Button-1>", lambda e: on_pick(Path(lb.get(lb.curselection()[0])) if lb.curselection() else None))


def show_sync_summary(parent, left: Path, right: Path):
    d = diff_trees(left, right)
    msg = (
        f"Only left: {len(d['only_left'])}\n"
        f"Only right: {len(d['only_right'])}\n"
        f"Newer on left: {len(d['newer_left'])}\n"
        f"Newer on right: {len(d['newer_right'])}\n"
        f"Same size/time: {len(d['same'])}"
    )
    messagebox.showinfo("Directory Sync Summary", msg, parent=parent)
    return d


def show_duplicates_dialog(parent, root: Path):
    groups = find_duplicates(root)
    lines = [f"{len(v)} files — {v[0].name}" for v in groups.values()]
    text = "\n".join(lines[:40]) if lines else "No duplicates found."
    messagebox.showinfo("Duplicate Files", text, parent=parent)