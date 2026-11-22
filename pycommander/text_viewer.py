"""Enhanced Lister (F3) and Editor (F4) windows."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from pathlib import Path

from pycommander.utils import format_size, get_file_bytes

ENCODINGS = ("auto", "utf-8", "utf-8-sig", "cp1252", "latin-1", "utf-16")

MAX_VIEW_BYTES = 4 * 1024 * 1024


def detect_text_content(raw: bytes, encoding: str = "auto") -> tuple[str, str]:
    """Return (text, encoding_used). Uses charset_normalizer when auto."""
    if encoding != "auto":
        return raw.decode(encoding), encoding
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        from charset_normalizer import from_bytes

        best = from_bytes(raw).best()
        if best is not None:
            return str(best), best.encoding or "utf-8"
    except Exception:
        pass
    return raw.decode("latin-1", errors="replace"), "latin-1"


def format_hex_dump(raw: bytes, max_bytes: int = 65536) -> str:
    lines = []
    cap = min(len(raw), max_bytes)
    for offset in range(0, cap, 16):
        chunk = raw[offset : offset + 16]
        hex_part = " ".join(f"{b:02X}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{offset:08X}  {hex_part:<47}  {ascii_part}")
    note = ""
    if len(raw) > max_bytes:
        note = f"\n[... {len(raw) - max_bytes:,} more bytes not shown ...]"
    return "Hex dump\n" + "=" * 72 + "\n" + "\n".join(lines) + note


class TextWorkbench(tk.Toplevel):
    """Tabbed-capable text viewer/editor with line numbers and search."""

    def __init__(
        self,
        parent,
        path: Path | None,
        *,
        editable: bool,
        on_saved=None,
        initial_content: str | None = None,
    ):
        super().__init__(parent)
        self.path = path
        self.editable = editable
        self.on_saved = on_saved
        self._modified = False
        self._hex_mode = False
        self._raw: bytes | None = None
        self._encoding = tk.StringVar(value="auto")
        self._wrap = tk.BooleanVar(value=False)
        self._find_case = tk.BooleanVar(value=False)

        name = path.name if path else "Untitled"
        self.title(f"{'Editor' if editable else 'Lister'} - {name}")
        self.geometry("960x640")
        self.minsize(520, 360)
        self.transient(parent)

        self._build_ui()
        if path:
            self._load_file()
        elif initial_content is not None:
            self.text.insert("1.0", initial_content)
            if not editable:
                self._apply_viewer_readonly()
            self._refresh_gutter()
            self._status.set(f"{len(initial_content):,} characters")
        self._apply_wrap()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        tb = ttk.Frame(self, padding=4)
        self._toolbar = tb
        tb.pack(fill=tk.X)

        ttk.Label(tb, text="Encoding:").pack(side=tk.LEFT, padx=(0, 4))
        enc = ttk.Combobox(tb, textvariable=self._encoding, values=ENCODINGS, width=10, state="readonly")
        enc.pack(side=tk.LEFT, padx=(0, 8))
        enc.bind("<<ComboboxSelected>>", lambda e: self._load_file() if self.path else None)

        ttk.Checkbutton(tb, text="Word wrap", variable=self._wrap, command=self._apply_wrap).pack(side=tk.LEFT, padx=4)

        if self.path and not self.editable:
            ttk.Button(tb, text="Hex view", command=self._toggle_hex).pack(side=tk.LEFT, padx=4)

        ttk.Button(tb, text="Find… Ctrl+F", command=self._show_find).pack(side=tk.LEFT, padx=4)
        if self.editable:
            ttk.Button(tb, text="Replace… Ctrl+H", command=self._show_replace).pack(side=tk.LEFT, padx=4)
            ttk.Button(tb, text="Go to line", command=self._goto_line).pack(side=tk.LEFT, padx=4)

        if self.editable:
            ttk.Button(tb, text="Save Ctrl+S", command=self._save).pack(side=tk.RIGHT, padx=2)
            ttk.Button(tb, text="Save & close", command=self._save_and_close).pack(side=tk.RIGHT, padx=2)

        # Find / replace bars
        self._find_frame = ttk.Frame(self, padding=(4, 0))
        self._find_var = tk.StringVar()
        ttk.Label(self._find_frame, text="Find:").pack(side=tk.LEFT)
        self._find_entry = ttk.Entry(self._find_frame, textvariable=self._find_var, width=36)
        self._find_entry.pack(side=tk.LEFT, padx=4)
        ttk.Button(self._find_frame, text="Next", command=self._find_next).pack(side=tk.LEFT, padx=2)
        ttk.Button(self._find_frame, text="Prev", command=self._find_prev).pack(side=tk.LEFT, padx=2)
        ttk.Button(self._find_frame, text="Close", command=self._hide_find).pack(side=tk.LEFT, padx=2)
        ttk.Checkbutton(self._find_frame, text="Match case", variable=self._find_case).pack(side=tk.LEFT, padx=8)
        self._find_entry.bind("<Return>", lambda e: (self._find_next(), "break")[1])
        self._find_entry.bind("<Shift-Return>", lambda e: (self._find_prev(), "break")[1])

        self._repl_frame = ttk.Frame(self, padding=(4, 0))
        self._repl_find = tk.StringVar()
        self._repl_with = tk.StringVar()
        ttk.Label(self._repl_frame, text="Find:").pack(side=tk.LEFT)
        ttk.Entry(self._repl_frame, textvariable=self._repl_find, width=20).pack(side=tk.LEFT, padx=2)
        ttk.Label(self._repl_frame, text="Replace:").pack(side=tk.LEFT, padx=(6, 0))
        ttk.Entry(self._repl_frame, textvariable=self._repl_with, width=20).pack(side=tk.LEFT, padx=2)
        ttk.Button(self._repl_frame, text="Replace", command=self._replace_one).pack(side=tk.LEFT, padx=2)
        ttk.Button(self._repl_frame, text="Replace all", command=self._replace_all).pack(side=tk.LEFT, padx=2)
        ttk.Button(self._repl_frame, text="Close", command=self._hide_replace).pack(side=tk.LEFT, padx=2)

        body = ttk.Frame(self)
        body.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)

        self._gutter = tk.Text(body, width=5, padx=4, takefocus=0, borderwidth=0, state=tk.DISABLED,
                               font=("Consolas", 10), background="#f0f0f0", foreground="#666666")
        self._gutter.pack(side=tk.LEFT, fill=tk.Y)

        self.text = tk.Text(
            body,
            wrap=tk.NONE,
            font=("Consolas", 10),
            undo=self.editable,
            borderwidth=1,
            relief=tk.SOLID,
        )
        vsb = ttk.Scrollbar(body, orient=tk.VERTICAL)
        def _on_scroll(first, last):
            vsb.set(first, last)
            self._gutter.yview_moveto(first)

        self.text.configure(yscrollcommand=_on_scroll)
        vsb.configure(command=self.text.yview)
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        hsb = ttk.Scrollbar(self, orient=tk.HORIZONTAL, command=self.text.xview)
        self.text.configure(xscrollcommand=hsb.set)
        hsb.pack(fill=tk.X, padx=4)

        self._status = tk.StringVar(value="")
        ttk.Label(self, textvariable=self._status, anchor=tk.W, padding=4).pack(fill=tk.X)

        self.text.tag_configure("find_hit", background="#fff59d", foreground="#000000")
        self.text.tag_raise("find_hit")

        self.text.bind("<KeyRelease>", self._on_text_changed)
        self.text.bind("<Button-1>", lambda e: self.after_idle(self._refresh_gutter))
        self.text.bind("<<Modified>>", self._on_modified)
        for w in (self, self.text):
            w.bind("<Control-f>", lambda e: (self._show_find(), "break"))
            w.bind("<Control-F>", lambda e: (self._show_find(), "break"))
        self.bind("<Control-h>", lambda e: self._show_replace() if self.editable else None)
        self.bind("<Control-H>", lambda e: self._show_replace() if self.editable else None)
        self.bind("<Control-s>", lambda e: self._save())
        self.bind("<Control-g>", lambda e: self._goto_line())
        self.bind("<F3>", lambda e: (self._find_next(), "break")[1])
        self.bind("<Shift-F3>", lambda e: (self._find_prev(), "break")[1])
        self.bind("<Escape>", lambda e: self._on_close())

    def _load_file(self):
        if not self.path:
            return
        try:
            raw = get_file_bytes(self.path)
        except Exception as e:
            messagebox.showerror("Open Error", str(e), parent=self)
            return

        truncated = False
        if len(raw) > MAX_VIEW_BYTES and not self.editable:
            raw = raw[:MAX_VIEW_BYTES]
            truncated = True
        elif len(raw) > MAX_VIEW_BYTES and self.editable:
            if not messagebox.askyesno(
                "Large file",
                f"File is {format_size(len(raw))}. Open in editor anyway?",
                parent=self,
            ):
                raw = raw[:MAX_VIEW_BYTES]
                truncated = True

        self._raw = raw
        self._hex_mode = False
        self._set_text_content(raw, truncated)

    def _set_text_content(self, raw: bytes, truncated: bool = False):
        if self._hex_mode:
            content = format_hex_dump(raw)
            enc_label = "hex"
        else:
            try:
                content, enc_label = detect_text_content(raw, self._encoding.get())
                self._encoding.set(enc_label if self._encoding.get() == "auto" else self._encoding.get())
            except Exception as e:
                content = format_hex_dump(raw)
                enc_label = f"hex ({e})"

        self.text.configure(state=tk.NORMAL)
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", content)
        if not self.editable:
            self._apply_viewer_readonly()
        else:
            self.text.edit_modified(False)
            self._modified = False

        self._refresh_gutter()
        try:
            size = self.path.stat().st_size if self.path and not find_archive_virtual(self.path) else len(raw)
        except OSError:
            size = len(raw)
        extra = " [truncated]" if truncated else ""
        self._status.set(f"{format_size(size)} | encoding: {enc_label}{extra}")
        self._update_title()

    def _toggle_hex(self):
        if not self._raw:
            return
        self._hex_mode = not self._hex_mode
        self._set_text_content(self._raw)

    def _apply_wrap(self):
        self.text.configure(wrap=tk.WORD if self._wrap.get() else tk.NONE)

    def _refresh_gutter(self):
        self._gutter.configure(state=tk.NORMAL)
        self._gutter.delete("1.0", tk.END)
        end_line = int(self.text.index("end-1c").split(".")[0])
        nums = "\n".join(str(i) for i in range(1, end_line + 1))
        self._gutter.insert("1.0", nums)
        self._gutter.configure(state=tk.DISABLED)

    def _on_text_changed(self, event=None):
        self.after_idle(self._refresh_gutter)
        if self.editable:
            pos = self.text.index(tk.INSERT)
            line, col = pos.split(".")
            self._status.set(f"Line {line}, col {int(col) + 1}")

    def _on_modified(self, event=None):
        if self.editable and self.text.edit_modified():
            self._modified = True
            self._update_title()

    def _update_title(self):
        name = self.path.name if self.path else "Untitled"
        star = " *" if self._modified else ""
        kind = "Editor" if self.editable else "Lister"
        self.title(f"{kind} - {name}{star}")

    def _apply_viewer_readonly(self):
        """NORMAL state keeps Text.search working; block typing instead of DISABLED."""
        self.text.configure(state=tk.NORMAL)
        if getattr(self, "_viewer_key_bound", False):
            return
        self._viewer_key_bound = True

        _allowed = frozenset(
            {
                "Left", "Right", "Up", "Down", "Home", "End",
                "Prior", "Next", "Tab", "Escape", "F3",
            }
        )

        def _on_viewer_key(event):
            if event.state & 0x4:  # Ctrl
                if event.keysym.lower() in ("c", "a", "f", "h", "g"):
                    return None
            if event.keysym in _allowed:
                return None
            if event.char and event.char.isprintable():
                return "break"
            if event.keysym in ("BackSpace", "Delete", "Return", "space"):
                return "break"
            return None

        self.text.bind("<KeyPress>", _on_viewer_key, add="+")

    def _show_find(self):
        self._hide_replace()
        self._find_frame.pack(fill=tk.X, after=self._toolbar)
        self._find_entry.focus_set()
        try:
            self._find_entry.selection_range(0, tk.END)
        except tk.TclError:
            pass

    def _hide_find(self):
        self._find_frame.pack_forget()

    def _show_replace(self):
        if not self.editable:
            return
        self._hide_find()
        self._repl_frame.pack(fill=tk.X, after=self._toolbar)

    def _hide_replace(self):
        self._repl_frame.pack_forget()

    def _search_opts(self) -> dict:
        if self._find_case.get():
            return {}
        return {"nocase": True}

    def _search_from(self, backwards: bool = False) -> bool:
        needle = self._find_var.get() or self._repl_find.get()
        if not needle:
            return False

        opts = self._search_opts()
        has_sel = bool(self.text.tag_ranges("sel"))
        if backwards:
            start = (
                self.text.index("sel.first - 1c")
                if has_sel
                else self.text.index(tk.INSERT)
            )
            idx = self.text.search(needle, start, backwards=True, stopindex="1.0", **opts)
            if not idx:
                idx = self.text.search(needle, tk.END, backwards=True, stopindex="1.0", **opts)
        else:
            start = self.text.index("sel.last") if has_sel else self.text.index(tk.INSERT)
            idx = self.text.search(needle, start, stopindex=tk.END, **opts)
            if not idx:
                idx = self.text.search(needle, "1.0", stopindex=tk.END, **opts)

        if not idx:
            self.text.tag_remove("find_hit", "1.0", tk.END)
            return False

        end = f"{idx}+{len(needle)}c"
        self.text.tag_remove("find_hit", "1.0", tk.END)
        self.text.tag_remove("sel", "1.0", tk.END)
        self.text.tag_add("find_hit", idx, end)
        self.text.tag_add("sel", idx, end)
        if backwards:
            self.text.mark_set(tk.INSERT, idx)
            self.text.mark_set("search_anchor", idx)
        else:
            self.text.mark_set(tk.INSERT, end)
            self.text.mark_set("search_anchor", idx)
        self.text.see(idx)
        self.text.focus_set()
        return True

    def _find_next(self):
        if self._find_var.get().strip() == "" and not self._find_frame.winfo_ismapped():
            self._show_find()
            return
        if not self._search_from(False):
            messagebox.showinfo("Find", "No match found.", parent=self)

    def _find_prev(self):
        if not self._search_from(True):
            messagebox.showinfo("Find", "No match found.", parent=self)

    def _replace_one(self):
        if not self.editable:
            return
        find = self._repl_find.get()
        if not find:
            return
        self._find_var.set(find)
        if not self.text.tag_ranges("sel"):
            if not self._search_from(False):
                messagebox.showinfo("Replace", "No match found.", parent=self)
                return
        sel_text = self.text.get("sel.first", "sel.last")
        if (sel_text == find) or (
            not self._find_case.get() and sel_text.lower() == find.lower()
        ):
            self.text.delete("sel.first", "sel.last")
            self.text.insert("sel.first", self._repl_with.get())
            self._modified = True
            self._update_title()
        self._search_from(False)

    def _replace_all(self):
        if not self.editable:
            return
        find = self._repl_find.get()
        repl = self._repl_with.get()
        if not find:
            return
        body = self.text.get("1.0", "end-1c")
        if self._find_case.get():
            count = body.count(find)
            new = body.replace(find, repl) if count else body
        else:
            import re

            new, count = re.subn(re.escape(find), repl, body, flags=re.IGNORECASE)
        if count == 0:
            messagebox.showinfo("Replace", "No matches.", parent=self)
            return
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", new)
        self._modified = True
        self._update_title()
        self._refresh_gutter()
        messagebox.showinfo("Replace", f"Replaced {count} occurrence(s).", parent=self)

    def _goto_line(self):
        n = simpledialog.askinteger("Go to line", "Line number:", parent=self, minvalue=1)
        if n:
            self.text.mark_set(tk.INSERT, f"{n}.0")
            self.text.see(f"{n}.0")
            self.text.focus_set()

    def _save(self) -> bool:
        if not self.editable or not self.path:
            return False
        enc = self._encoding.get()
        if enc == "auto":
            enc = "utf-8"
        try:
            data = self.text.get("1.0", "end-1c")
            self.path.write_text(data, encoding=enc, newline="\n")
            self.text.edit_modified(False)
            self._modified = False
            self._update_title()
            if self.on_saved:
                self.on_saved()
            return True
        except Exception as e:
            messagebox.showerror("Save Error", str(e), parent=self)
            return False

    def _save_and_close(self):
        if self._save():
            self.destroy()

    def _on_close(self):
        if self._modified and self.editable:
            ans = messagebox.askyesnocancel(
                "Unsaved changes", "Save changes before closing?", parent=self
            )
            if ans is None:
                return
            if ans and not self._save():
                return
        self.destroy()


def find_archive_virtual(path: Path) -> bool:
    from pycommander.archives import find_archive_root

    return find_archive_root(path) is not None


def open_viewer(parent, path: Path, on_saved=None):
    TextWorkbench(parent, path, editable=False, on_saved=on_saved)


def open_editor(parent, path: Path, on_saved=None):
    TextWorkbench(parent, path, editable=True, on_saved=on_saved)


def open_text_window(parent, title: str, content: str, editable: bool = False):
    win = TextWorkbench(parent, None, editable=editable, initial_content=content)
    win.title(title)