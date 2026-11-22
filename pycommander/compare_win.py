"""Compare by content window."""
import os
import sys
import shutil
import stat
import subprocess
import threading
import datetime
import string
import re
import zipfile
import tarfile
import difflib
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
from pathlib import Path


from pycommander.utils import format_size, get_file_text

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
            # Line-level context (pale); inline_* tags mark the exact changed spans
            t.tag_configure("diff_replace", background="#ffe8e8", foreground="#333333")
            t.tag_configure("diff_delete", background="#fff0e0", foreground="#804000")
            t.tag_configure("diff_insert", background="#e8f8ee", foreground="#006622")
            t.tag_configure("diff_blank", background="#f3f3f3", foreground="#aaaaaa")
            t.tag_configure("inline_del", background="#ff6b6b", foreground="#ffffff", font=("Consolas", 10, "bold"))
            t.tag_configure("inline_ins", background="#2ecc71", foreground="#ffffff", font=("Consolas", 10, "bold"))
            t.tag_configure("inline_chg", background="#f1c40f", foreground="#1a1a1a", font=("Consolas", 10, "bold"))
            t.tag_configure("diff_focus", background="#fff3cd")
            t.tag_raise("inline_del")
            t.tag_raise("inline_ins")
            t.tag_raise("inline_chg")
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

            row_tag = f"row_{r_idx}"
            if tag == "equal":
                self.text1.insert(tk.END, l1 + "\n")
                self.text2.insert(tk.END, l2 + "\n")
            elif tag == "replace":
                if n1 != "" and n2 != "":
                    self._insert_inline_diff(l1, l2, row_tag)
                else:
                    tag1 = "diff_replace" if n1 != "" else "diff_blank"
                    tag2 = "diff_replace" if n2 != "" else "diff_blank"
                    val1 = l1 if n1 != "" else "~~~"
                    val2 = l2 if n2 != "" else "~~~"
                    self.text1.insert(tk.END, val1 + "\n", (tag1, row_tag))
                    self.text2.insert(tk.END, val2 + "\n", (tag2, row_tag))
            elif tag == "delete":
                self.text1.insert(tk.END, l1 + "\n", ("diff_delete", row_tag))
                self.text2.insert(tk.END, "~~~\n", ("diff_blank", row_tag))
            elif tag == "insert":
                self.text1.insert(tk.END, "~~~\n", ("diff_blank", row_tag))
                self.text2.insert(tk.END, l2 + "\n", ("diff_insert", row_tag))

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

    def _tokenize_for_diff(self, text: str) -> list[str]:
        """Split into words and separators so inline diffs prefer whole words."""
        return re.findall(r"\w+|\W+", text) if text else []

    def _insert_inline_diff(self, l1: str, l2: str, row_tag: str):
        """Insert a replace pair with color on changed words / spans only."""
        tokens1 = self._tokenize_for_diff(l1)
        tokens2 = self._tokenize_for_diff(l2)
        matcher = difflib.SequenceMatcher(None, tokens1, tokens2)

        for op, i1, i2, j1, j2 in matcher.get_opcodes():
            left = "".join(tokens1[i1:i2])
            right = "".join(tokens2[j1:j2])
            if op == "equal":
                if left:
                    self.text1.insert(tk.END, left, ("diff_replace", row_tag))
                if right:
                    self.text2.insert(tk.END, right, ("diff_replace", row_tag))
            elif op == "replace":
                # Character-level only when the two spans look alike; else whole word/phrase
                similar = (
                    left
                    and right
                    and max(len(left), len(right)) <= 48
                    and difflib.SequenceMatcher(None, left, right).ratio() >= 0.45
                )
                if similar:
                    self._insert_char_spans(left, right, row_tag)
                else:
                    if left:
                        self.text1.insert(tk.END, left, ("diff_replace", "inline_chg", row_tag))
                    if right:
                        self.text2.insert(tk.END, right, ("diff_replace", "inline_chg", row_tag))
            elif op == "delete":
                if left:
                    self.text1.insert(tk.END, left, ("diff_replace", "inline_del", row_tag))
            elif op == "insert":
                if right:
                    self.text2.insert(tk.END, right, ("diff_replace", "inline_ins", row_tag))

        self.text1.insert(tk.END, "\n", ("diff_replace", row_tag))
        self.text2.insert(tk.END, "\n", ("diff_replace", row_tag))

    def _insert_char_spans(self, s1: str, s2: str, row_tag: str):
        """Character-level highlight inside a replaced word/phrase."""
        matcher = difflib.SequenceMatcher(None, s1, s2)
        for op, i1, i2, j1, j2 in matcher.get_opcodes():
            left, right = s1[i1:i2], s2[j1:j2]
            if op == "equal":
                if left:
                    self.text1.insert(tk.END, left, ("diff_replace", row_tag))
                if right:
                    self.text2.insert(tk.END, right, ("diff_replace", row_tag))
            elif op == "replace":
                if left:
                    self.text1.insert(tk.END, left, ("diff_replace", "inline_chg", row_tag))
                if right:
                    self.text2.insert(tk.END, right, ("diff_replace", "inline_chg", row_tag))
            elif op == "delete":
                if left:
                    self.text1.insert(tk.END, left, ("diff_replace", "inline_del", row_tag))
            elif op == "insert":
                if right:
                    self.text2.insert(tk.END, right, ("diff_replace", "inline_ins", row_tag))

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

