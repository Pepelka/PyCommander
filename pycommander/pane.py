"""Single file browser pane."""
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


from pycommander.utils import format_size, format_datetime, get_available_drives, get_file_bytes, get_file_text
from pycommander.archives import is_archive_file, find_archive_root, list_archive_entries
from pycommander.paths import get_path_info
from pycommander.selection import resolve_selection_paths, filter_entries, is_hidden_entry
from pycommander.session_paths import normalize_stored_path

class FilePane(ttk.Frame):
    """Represents one side (left or right) of the dual-pane file browser."""

    def __init__(self, parent, app, initial_path: Path):
        super().__init__(parent, padding=3)
        self.app = app
        self.current_path = normalize_stored_path(initial_path)
        self.sort_col = "name"
        self.sort_reverse = False
        self.is_active = False
        self.marked_items: set[str] = set()

        # Path history tracking
        self.history_stack: list[Path] = [self.current_path]
        self.history_index: int = 0
        self.path_history: list[Path] = [self.current_path]
        self._cached_entries: list[dict] = []
        self._entries_truncated = False
        self.quick_filter_var = tk.StringVar(value="")
        self._filter_after: str | None = None
        self._status_after: str | None = None
        self._quick_view_after: str | None = None

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

        filter_row = ttk.Frame(self)
        filter_row.pack(fill=tk.X, pady=(0, 2))
        ttk.Label(filter_row, text="Filter:").pack(side=tk.LEFT, padx=(0, 4))
        self.filter_entry = ttk.Entry(filter_row, textvariable=self.quick_filter_var)
        self.filter_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.quick_filter_var.trace_add("write", self._on_filter_changed)

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
        self.tree.bind("<Button-1>", self._on_tree_button1)
        self.tree.bind("<Double-1>", self._on_activate_item)
        self.tree.bind("<Return>", self._on_activate_item)
        self.tree.bind("<BackSpace>", lambda e: self.go_up())
        self.tree.bind("<Tab>", self._on_tab_key)
        self.tree.bind("<Insert>", self._on_insert_key)
        self.tree.bind("<space>", self._on_space_key)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.update_status())
        self.tree.bind("<Button-3>", self._on_right_click)
        # macOS / some setups use Button-2 or Control-Click for context menu
        self.tree.bind("<Control-Button-1>", self._on_right_click)
        self.tree.bind("<Shift-F10>", self._on_context_menu_key)
        self.tree.bind("<App>", self._on_context_menu_key)  # Menu key on Windows keyboards

        # Bottom status label
        self.status_var = tk.StringVar(value="")
        self.status_lbl = ttk.Label(self, textvariable=self.status_var, anchor=tk.W)
        self.status_lbl.pack(fill=tk.X, pady=(2, 0))
        self.quick_view = tk.Text(self, height=4, wrap=tk.WORD, font=("Consolas", 9))
        self.tree.bind("<<TreeviewSelect>>", self._on_select_quick_view, add="+")

    def _on_tree_button1(self, event):
        if self.app.active_pane is not self:
            self.app.set_active_pane(self)

    def _on_filter_changed(self, *_):
        if self._filter_after:
            try:
                self.after_cancel(self._filter_after)
            except Exception:
                pass
        self._filter_after = self.after(250, self._refresh_from_filter)

    def _refresh_from_filter(self):
        self._filter_after = None
        self.refresh()

    def _on_select_quick_view(self, event=None):
        if not getattr(self.app, "app_config", None) or not self.app.app_config.get("quick_view_enabled"):
            if self.quick_view.winfo_ismapped():
                self.quick_view.pack_forget()
            return
        if self._quick_view_after:
            try:
                self.after_cancel(self._quick_view_after)
            except Exception:
                pass
        self._quick_view_after = self.after(120, self._render_quick_view)

    def _render_quick_view(self):
        self._quick_view_after = None
        if not self.quick_view.winfo_ismapped():
            self.quick_view.pack(fill=tk.X, pady=(2, 0))
        path = self.get_focused_path()
        self.quick_view.configure(state=tk.NORMAL)
        self.quick_view.delete("1.0", tk.END)
        if not path or self.is_dir(path):
            self.quick_view.insert(tk.END, "(no file preview)")
        else:
            try:
                raw = get_file_bytes(path)[:2048]
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    text = "[binary preview unavailable]"
                self.quick_view.insert(tk.END, text)
            except Exception as e:
                self.quick_view.insert(tk.END, str(e))
        self.quick_view.configure(state=tk.DISABLED)

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

    def _on_right_click(self, event):
        """Right-click: activate pane, adjust selection, show context menu."""
        self.app.set_active_pane(self)
        row = self.tree.identify_row(event.y)
        if row:
            self._prepare_context_selection(row)
        self.show_context_menu(event.x_root, event.y_root)
        return "break"

    def _on_context_menu_key(self, event=None):
        """Shift+F10 / Menu key: context menu at the focused row."""
        self.app.set_active_pane(self)
        focus_id = self.tree.focus()
        if focus_id:
            self._prepare_context_selection(focus_id)
            bbox = self.tree.bbox(focus_id)
            if bbox:
                x = self.tree.winfo_rootx() + bbox[0] + min(40, bbox[2] // 2)
                y = self.tree.winfo_rooty() + bbox[1] + bbox[3]
            else:
                x = self.tree.winfo_rootx() + 40
                y = self.tree.winfo_rooty() + 40
        else:
            x = self.tree.winfo_rootx() + 40
            y = self.tree.winfo_rooty() + 40
        self.show_context_menu(x, y)
        return "break"

    def _prepare_context_selection(self, row: str):
        """Ensure right-clicked / focused row is part of the working selection."""
        self.tree.focus(row)
        self.tree.see(row)
        if row == "..":
            self.tree.selection_set(row)
            self.update_status()
            return

        if self.marked_items:
            if row not in self.marked_items:
                # Clicked outside marks → clear marks and use this item
                previously = list(self.marked_items)
                self.marked_items.clear()
                for iid in previously:
                    self._update_item_visual(iid)
                self.tree.selection_set(row)
            else:
                # Keep marks; also sync tree selection to marked rows for visual clarity
                marked_rows = [iid for iid in self.tree.get_children() if iid in self.marked_items]
                if marked_rows:
                    self.tree.selection_set(marked_rows)
        else:
            current_sel = self.tree.selection()
            if row not in current_sel:
                self.tree.selection_set(row)
        self.update_status()

    @staticmethod
    def _ctx_label(name: str, hotkey: str = "") -> str:
        """Menu label with a space between command name and hotkey."""
        return f"{name} {hotkey}" if hotkey else name

    def show_context_menu(self, x: int, y: int):
        """Context menu modeled after Explorer / Total Commander / Far."""
        paths = self.get_selected_paths()
        focus = self.get_focused_path()
        n = len(paths)
        single = paths[0] if n == 1 else None
        has_items = n > 0
        in_archive = find_archive_root(self.current_path) is not None
        can_paste = bool(self.app.file_clipboard and self.app.file_clipboard.get("paths")) and not in_archive

        sel_for_mark = [s for s in self.tree.selection() if s != ".."]
        if not sel_for_mark:
            f = self.tree.focus()
            if f and f != "..":
                sel_for_mark = [f]
        all_marked = bool(sel_for_mark) and all(s in self.marked_items for s in sel_for_mark)

        menu = tk.Menu(self, tearoff=0)
        lbl = self._ctx_label
        en = tk.NORMAL
        dis = tk.DISABLED

        # --- Open / Open with / View / Edit (Explorer + Commander) ---
        can_open = bool(
            single
            and (
                self.is_dir(single)
                or is_archive_file(single)
                or not find_archive_root(single)
            )
        )
        can_open_with = bool(
            single and not self.is_dir(single) and not find_archive_root(single)
        )
        menu.add_command(
            label="Open",
            command=self._on_activate_item,
            state=en if can_open else dis,
        )
        open_with_menu = tk.Menu(menu, tearoff=0)
        open_with_menu.add_command(
            label="Choose default program...",
            command=lambda: self._open_with_system_dialog(single),
            state=en if can_open_with else dis,
        )
        open_with_menu.add_command(
            label="Choose another program...",
            command=lambda: self._open_with_pick_program(single),
            state=en if can_open_with else dis,
        )
        menu.add_cascade(
            label="Open with",
            menu=open_with_menu,
            state=en if can_open_with else dis,
        )
        menu.add_command(
            label=lbl("View", "F3"),
            command=self.app.action_view,
            state=en if focus else dis,
        )
        menu.add_command(
            label=lbl("Edit", "F4"),
            command=self.app.action_edit,
            state=en if (single and not self.is_dir(single) and not in_archive) else dis,
        )
        menu.add_separator()

        # --- Clipboard (Windows Explorer style) ---
        menu.add_command(
            label=lbl("Cut", "Ctrl+X"),
            command=self.app.action_clipboard_cut,
            state=en if has_items and not in_archive else dis,
        )
        menu.add_command(
            label=lbl("Copy", "Ctrl+C"),
            command=self.app.action_clipboard_copy,
            state=en if has_items else dis,
        )
        menu.add_command(
            label=lbl("Paste", "Ctrl+V"),
            command=self.app.action_clipboard_paste,
            state=en if can_paste else dis,
        )
        menu.add_separator()

        # --- Panel operations (Total Commander / Far) ---
        menu.add_command(
            label=lbl("Copy to Other Panel", "F5"),
            command=self.app.action_copy,
            state=en if has_items else dis,
        )
        menu.add_command(
            label=lbl("Move to Other Panel", "F6"),
            command=self.app.action_move,
            state=en if has_items and not in_archive else dis,
        )
        menu.add_separator()

        # --- Delete / Rename ---
        menu.add_command(
            label=lbl("Delete", "Del"),
            command=self.app.action_delete,
            state=en if has_items and not in_archive else dis,
        )
        menu.add_command(
            label=lbl("Rename", "F2"),
            command=self.app.action_rename,
            state=en if (single and not in_archive) else dis,
        )
        menu.add_separator()

        # --- New ---
        menu.add_command(
            label=lbl("New Folder", "F7"),
            command=self.app.action_mkdir,
            state=en if not in_archive else dis,
        )
        if os.name == "nt":
            menu.add_command(
                label="Create Shortcut",
                command=self.app.action_create_shortcut,
                state=en if has_items and not in_archive else dis,
            )
        menu.add_separator()

        # --- Tools ---
        menu.add_command(
            label=lbl("Compare by Content...", "Ctrl+Alt+C"),
            command=self.app.action_compare,
        )
        menu.add_command(
            label="Copy as Path",
            command=lambda: self._copy_paths_to_clipboard(paths if has_items else [self.current_path]),
        )
        menu.add_command(
            label="Copy Filename(s)",
            command=lambda: self._copy_filenames_to_clipboard(paths),
            state=en if has_items else dis,
        )
        menu.add_separator()

        # --- Mark (Commander) ---
        menu.add_command(
            label="Unmark" if all_marked else "Mark",
            command=lambda: self._context_toggle_mark(sel_for_mark),
            state=en if sel_for_mark else dis,
        )
        menu.add_command(label=lbl("Select All", "Ctrl+A"), command=self.app.action_select_all)
        menu.add_command(label=lbl("Clear Selection", "Ctrl+D"), command=self.app.action_unselect_all)
        menu.add_separator()

        # --- System ---
        menu.add_command(
            label=lbl("Open Command Prompt Here", "F9"),
            command=self.app.action_open_terminal,
            state=en if not in_archive else dis,
        )
        if os.name == "nt":
            menu.add_command(
                label="Show in Explorer",
                command=self._open_in_file_manager,
                state=en if not in_archive else dis,
            )
        else:
            menu.add_command(
                label="Open Containing Folder",
                command=self._open_in_file_manager,
                state=en if not in_archive else dis,
            )
        menu.add_command(label=lbl("Refresh", "Ctrl+R"), command=self.refresh)
        menu.add_separator()
        menu.add_command(
            label=lbl("Properties", "Alt+Enter"),
            command=self.app.action_properties,
            state=en if focus else dis,
        )

        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _open_with_system_dialog(self, path: Path | None):
        """Open the OS 'Open with' dialog (Windows) or pick an app."""
        if not path or self.is_dir(path):
            return
        if find_archive_root(path):
            messagebox.showinfo(
                "Archive",
                "Open with is not supported for files inside archives.\nExtract the file first (F5).",
                parent=self.app,
            )
            return
        try:
            if os.name == "nt":
                # Native Windows "Open with" dialog
                subprocess.Popen(
                    ["rundll32", "shell32.dll,OpenAs_RunDLL", str(path)],
                    cwd=str(path.parent),
                )
            else:
                # No universal "Open with" dialog — fall back to choosing a program
                self._open_with_pick_program(path)
        except Exception as e:
            messagebox.showerror("Open with", str(e), parent=self.app)

    def _open_with_pick_program(self, path: Path | None):
        """Let the user choose an executable and open the file with it."""
        if not path or self.is_dir(path):
            return
        if find_archive_root(path):
            messagebox.showinfo(
                "Archive",
                "Open with is not supported for files inside archives.\nExtract the file first (F5).",
                parent=self.app,
            )
            return
        filetypes = [("Programs", "*.exe;*.bat;*.cmd;*.com"), ("All files", "*.*")] if os.name == "nt" else [
            ("All files", "*")
        ]
        init_dir = os.environ.get("ProgramFiles", str(Path.home())) if os.name == "nt" else "/usr/bin"
        program = filedialog.askopenfilename(
            parent=self.app,
            title=f"Open '{path.name}' with...",
            initialdir=init_dir,
            filetypes=filetypes,
        )
        if not program:
            return
        try:
            subprocess.Popen([program, str(path)], cwd=str(path.parent))
        except Exception as e:
            messagebox.showerror("Open with", f"Could not start program:\n{e}", parent=self.app)

    def _context_toggle_mark(self, iids: list[str]):
        if not iids:
            return
        all_marked = all(iid in self.marked_items for iid in iids)
        for iid in iids:
            if all_marked:
                self.marked_items.discard(iid)
            else:
                self.marked_items.add(iid)
            self._update_item_visual(iid)
        self.update_status()

    def _copy_paths_to_clipboard(self, paths: list[Path]):
        if not paths:
            return
        text = "\n".join(str(p) for p in paths)
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.update_idletasks()
            self.status_var.set(f"Copied {len(paths)} path(s) to clipboard")
        except tk.TclError as e:
            messagebox.showerror("Clipboard Error", str(e), parent=self.app)

    def _copy_filenames_to_clipboard(self, paths: list[Path]):
        if not paths:
            return
        text = "\n".join(p.name for p in paths)
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.update_idletasks()
            self.status_var.set(f"Copied {len(paths)} filename(s) to clipboard")
        except tk.TclError as e:
            messagebox.showerror("Clipboard Error", str(e), parent=self.app)

    def _open_in_file_manager(self):
        """Reveal current folder (or selected item) in the OS file manager."""
        if find_archive_root(self.current_path):
            messagebox.showinfo(
                "Archive",
                "Cannot open archive virtual folders in the system file manager.",
                parent=self.app,
            )
            return
        paths = self.get_selected_paths()
        target = paths[0] if len(paths) == 1 else self.current_path
        try:
            if os.name == "nt":
                if target.is_file():
                    subprocess.Popen(["explorer", "/select,", str(target)])
                else:
                    os.startfile(str(target if target.is_dir() else target.parent))
            elif sys.platform == "darwin":
                if target.is_file():
                    subprocess.Popen(["open", "-R", str(target)])
                else:
                    subprocess.Popen(["open", str(target if target.is_dir() else target.parent)])
            else:
                folder = target if target.is_dir() else target.parent
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as e:
            messagebox.showerror("Open Error", str(e), parent=self.app)

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
        if hasattr(self.app, "persist_pane_paths"):
            self.app.persist_pane_paths()

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
                show_hidden = bool(getattr(self.app, "app_config", None) and self.app.app_config.get("show_hidden"))
                with os.scandir(self.current_path) as it:
                    for entry in it:
                        if is_hidden_entry(entry.name, Path(entry.path), show_hidden):
                            continue
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

        self._cached_entries = list(entries)
        fq = self.quick_filter_var.get().strip()
        if fq:
            entries = filter_entries(entries, fq)

        # Keep only marks for entries that still exist
        existing_names = {e["name"] for e in self._cached_entries}
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

        cap = int(getattr(self.app, "app_config", None) and self.app.app_config.get("refresh_cap") or 5000)
        combined = dirs + files
        self._entries_truncated = len(combined) > cap
        if self._entries_truncated:
            combined = combined[:cap]
            dirs = [e for e in combined if e["is_dir"]]
            files = [e for e in combined if not e["is_dir"]]

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
        if self._status_after:
            try:
                self.after_cancel(self._status_after)
            except Exception:
                pass
        self._status_after = self.after(30, lambda: self._update_status_impl(num_dirs, num_files, total_size))

    def _update_status_impl(self, num_dirs=None, num_files=None, total_size=None):
        self._status_after = None
        if self.marked_items:
            selected = list(self.marked_items)
        else:
            selected = [s for s in self.tree.selection() if s != ".."]
        sel_size = 0
        arch_info = find_archive_root(self.current_path)
        arch_index: dict[str, int] = {}
        if arch_info:
            for e in list_archive_entries(arch_info[0], arch_info[1]):
                if not e["is_dir"]:
                    arch_index[e["name"]] = e["size"]
        for name in selected:
            p = self.current_path / name
            try:
                if arch_info:
                    sel_size += arch_index.get(name, 0)
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
        highlighted = [s for s in self.tree.selection() if s != ".."]
        n_mark = len(self.marked_items)
        n_hl = len(highlighted)
        sel_label = f"Marked {n_mark}" if n_mark else f"Selected {n_hl}"
        trunc = " [list truncated]" if self._entries_truncated else ""
        self.status_var.set(
            f"{arch_label}{sel_label}: {len(selected)} item(s) ({format_size(sel_size)}){trunc}   |   {free_str}"
        )

    def get_selected_paths(self) -> list[Path]:
        """Return list of marked/selected Paths (excluding '..'). Falls back to focused item."""
        prefer = bool(getattr(self.app, "app_config", None) and self.app.app_config.get("prefer_marks_for_ops", True))
        children = [c for c in self.tree.get_children() if c != ".."]
        return resolve_selection_paths(
            self.current_path,
            self.marked_items,
            list(self.tree.selection()),
            children,
            self.tree.focus(),
            prefer_marks=prefer,
        )

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

