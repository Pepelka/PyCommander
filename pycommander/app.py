"""Main application window."""
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

from pycommander.archives import find_archive_root, list_archive_entries, extract_archive_item, is_archive_file
from pycommander.utils import format_size, get_file_bytes, get_file_text
from pycommander.paths import get_path_info
from pycommander.conflict import ConflictResolver
from pycommander.operations import copy_file_with_conflict, copy_dir_with_conflict, move_with_conflict
from pycommander.pane import FilePane
from pycommander.compare_win import FileCompareWindow
from pycommander.config import AppConfig
from pycommander.delete_ops import delete_paths
from pycommander.dialogs import (
    OperationProgressDialog,
    show_multirename_dialog,
    show_search_dialog,
    show_sync_summary,
    show_duplicates_dialog,
)
from pycommander.compare_logic import files_equal
from pycommander.archives import create_zip_from_selection
from pycommander import plugins as plugin_loader
from pycommander.shell_clipboard import (
    get_clipboard_file_paths,
    set_clipboard_files,
    clipboard_has_files,
)
import logging

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
except ImportError:  # pragma: no cover
    Observer = None  # type: ignore
    FileSystemEventHandler = object  # type: ignore

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:  # pragma: no cover
    DND_FILES = None
    TkinterDnD = None

LOG = logging.getLogger("pycommander")

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
        # Explorer-style file clipboard: {"mode": "copy"|"cut", "paths": [Path, ...]}
        self.file_clipboard: dict | None = None
        self.app_config = AppConfig()
        self._delete_permanent = False
        self._fs_observer = None
        self._watch_path: str | None = None
        self._watch_refresh_after: str | None = None
        logging.basicConfig(level=logging.INFO)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_menu()
        self._build_layout()
        self._bind_shortcuts()
        self._try_setup_dnd()

        self.active_pane: FilePane = self.left_pane
        self.set_active_pane(self.left_pane)
        if self._fs_observer is None and Observer is not None:
            self._watch_path = None
            self._setup_watchdog(self.left_pane.current_path)
        self.left_pane.tree.focus_set()
        plugin_loader.load_plugins(self)

    def _build_menu(self):
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open / Enter", command=lambda: self.active_pane._on_activate_item())
        file_menu.add_command(label="View (F3)", command=self.action_view)
        file_menu.add_command(label="Edit (F4)", command=self.action_edit)
        file_menu.add_separator()
        file_menu.add_command(label="Cut (Ctrl+X)", command=self.action_clipboard_cut)
        file_menu.add_command(label="Copy (Ctrl+C)", command=self.action_clipboard_copy)
        file_menu.add_command(label="Paste (Ctrl+V)", command=self.action_clipboard_paste)
        file_menu.add_separator()
        file_menu.add_command(label="Copy to Other Panel (F5)", command=self.action_copy)
        file_menu.add_command(label="Move to Other Panel (F6)", command=self.action_move)
        file_menu.add_command(label="Rename (F2)", command=self.action_rename)
        file_menu.add_command(label="Delete (F8 / Del)", command=self.action_delete)
        file_menu.add_separator()
        file_menu.add_command(label="New Folder (F7)", command=self.action_mkdir)
        if os.name == "nt":
            file_menu.add_command(label="Create Shortcut", command=self.action_create_shortcut)
        file_menu.add_separator()
        file_menu.add_command(label="Compare by Content... (Ctrl+Alt+C)", command=self.action_compare)
        file_menu.add_command(label="Properties (Alt+Enter)", command=self.action_properties)
        file_menu.add_separator()
        file_menu.add_command(label="Exit (F10)", command=self._on_close)
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

        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_command(
            label="Show Hidden Files",
            command=self.toggle_show_hidden,
        )
        view_menu.add_command(label="Quick Filter (Ctrl+F)", command=self._focus_active_filter)
        view_menu.add_command(label="Quick View Panel", command=self.toggle_quick_view)
        menubar.add_cascade(label="View", menu=view_menu)

        cmd_menu = tk.Menu(menubar, tearoff=0)
        cmd_menu.add_command(label="Sync Directory Summary", command=self.action_sync_dirs)
        cmd_menu.add_command(label="Multi-Rename…", command=self.action_multirename)
        cmd_menu.add_command(label="Search Files…", command=self.action_search)
        cmd_menu.add_command(label="Find Duplicates…", command=self.action_duplicates)
        cmd_menu.add_command(label="Create ZIP from Selection", command=self.action_create_zip)
        cmd_menu.add_command(label="Add Bookmark", command=self.action_bookmark_add)
        self.bookmarks_menu = tk.Menu(cmd_menu, tearoff=0)
        cmd_menu.add_cascade(label="Bookmarks", menu=self.bookmarks_menu)
        self._rebuild_bookmarks_menu()
        menubar.add_cascade(label="Commands", menu=cmd_menu)

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

        proj = Path(__file__).resolve().parent.parent
        start_left = Path(self.app_config.get("last_left_path") or proj)
        start_right = Path(self.app_config.get("last_right_path") or Path.home())
        if not start_left.is_dir():
            start_left = proj

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
            ("F10 Quit", self._on_close),
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
        self.bind("<Shift-Delete>", lambda e: (self.action_delete(permanent=True), "break")[1])
        self.bind("<Control-f>", lambda e: self._focus_active_filter())
        self.bind("<Control-F>", lambda e: self._focus_active_filter())
        for i in range(1, 10):
            self.bind(f"<Control-Key-{i}>", lambda e, n=i: self.action_bookmark_go(n - 1))
        self.bind("<F9>", lambda e: self.action_open_terminal())
        self.bind("<F10>", lambda e: self._on_close())
        self.bind("<Control-r>", lambda e: self.refresh_both())
        self.bind("<Control-a>", lambda e: self.action_select_all())
        self.bind("<Control-d>", lambda e: self.action_unselect_all())
        self.bind("<Control-x>", lambda e: self._shortcut_clipboard("cut"))
        self.bind("<Control-c>", lambda e: self._shortcut_clipboard("copy"))
        self.bind("<Control-v>", lambda e: self._shortcut_clipboard("paste"))
        self.bind("<KP_Multiply>", lambda e: self.action_invert_selection())
        self.bind("<asterisk>", lambda e: self.action_invert_selection())
        self.bind("<equal>", lambda e: self.action_sync_panes())
        self.bind("<Alt-Return>", lambda e: self.action_properties())
        self.bind("<Control-Alt-c>", lambda e: self.action_compare())
        self.bind("<Control-Alt-C>", lambda e: self.action_compare())
        self.bind("<Alt-Left>", lambda e: self.active_pane.history_back())
        self.bind("<Alt-Right>", lambda e: self.active_pane.history_forward())
        self.bind("<Alt-Down>", lambda e: self.active_pane.show_history_menu())

    def _on_close(self):
        self.app_config.flush()
        if self._fs_observer:
            try:
                self._fs_observer.stop()
            except Exception:
                pass
        self.destroy()

    def set_active_pane(self, pane: FilePane):
        if getattr(self, "active_pane", None) is pane:
            return
        self.active_pane = pane
        self.left_pane.set_active_visual(pane is self.left_pane)
        self.right_pane.set_active_visual(pane is self.right_pane)
        self.cmd_prompt_var.set(f"{pane.current_path}>")
        path_str = str(pane.current_path)
        if pane is self.left_pane:
            self.app_config.set("last_left_path", path_str)
        else:
            self.app_config.set("last_right_path", path_str)
        self._setup_watchdog(pane.current_path)

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

    def _focus_is_text_input(self) -> bool:
        w = self.focus_get()
        if w is None:
            return False
        cls = w.winfo_class()
        return cls in ("Entry", "TEntry", "Text", "TCombobox", "Combobox")

    def _shortcut_clipboard(self, action: str):
        """Ctrl+X/C/V — skip when typing in path/command fields."""
        if self._focus_is_text_input():
            return
        if action == "cut":
            self.action_clipboard_cut()
        elif action == "copy":
            self.action_clipboard_copy()
        elif action == "paste":
            self.action_clipboard_paste()

    def action_clipboard_cut(self):
        """Explorer-style Cut: remember selection for Paste (move)."""
        if find_archive_root(self.active_pane.current_path):
            messagebox.showinfo("Archive Notice", "Cut is not supported inside archives.", parent=self)
            return
        sources = self.active_pane.get_selected_paths()
        if not sources:
            return
        self.file_clipboard = {"mode": "cut", "paths": list(sources)}
        set_clipboard_files(sources, cut=True)
        self.active_pane.status_var.set(f"Cut {len(sources)} item(s) — use Paste (Ctrl+V)")

    def action_clipboard_copy(self):
        """Explorer-style Copy: remember selection for Paste (copy)."""
        sources = self.active_pane.get_selected_paths()
        if not sources:
            return
        self.file_clipboard = {"mode": "copy", "paths": list(sources)}
        set_clipboard_files(sources, cut=False)
        self.active_pane.status_var.set(f"Copied {len(sources)} item(s) — use Paste (Ctrl+V)")

    def action_clipboard_paste(self):
        """Explorer-style Paste into the active pane's current folder."""
        clip = self.file_clipboard
        if (not clip or not clip.get("paths")) and clipboard_has_files():
            paths = get_clipboard_file_paths()
            if paths:
                clip = {"mode": "copy", "paths": paths}
                self.file_clipboard = clip
        if not clip or not clip.get("paths"):
            return
        dest_dir = self.active_pane.current_path
        if find_archive_root(dest_dir):
            messagebox.showwarning(
                "Archive Notice",
                "Paste into archives is not supported.",
                parent=self,
            )
            return

        mode = clip.get("mode", "copy")
        sources = [Path(p) for p in clip["paths"]]
        # Drop missing sources
        sources = [p for p in sources if p.exists() or find_archive_root(p)]
        if not sources:
            self.file_clipboard = None
            messagebox.showinfo("Paste", "Clipboard items no longer exist.", parent=self)
            return

        resolver = ConflictResolver(self)
        errors: list[str] = []
        for src in sources:
            if resolver.cancelled:
                break
            try:
                if mode == "cut":
                    if find_archive_root(src):
                        errors.append(f"{src.name}: cannot move out of archive via Paste (use F5 Copy)")
                        continue
                    dst = dest_dir / src.name
                    if src.resolve() == dst.resolve():
                        continue
                    # Avoid moving a folder into itself
                    try:
                        if src.is_dir() and dest_dir.resolve().is_relative_to(src.resolve()):
                            errors.append(f"{src.name}: cannot move folder into itself")
                            continue
                    except (OSError, ValueError):
                        pass
                    result = move_with_conflict(src, dst, resolver)
                    if result == "cancelled":
                        break
                else:
                    arch_info = find_archive_root(src)
                    if arch_info:
                        ok = extract_archive_item(arch_info[0], arch_info[1], dest_dir, resolver)
                        if not ok and resolver.cancelled:
                            break
                    elif src.is_dir():
                        result = copy_dir_with_conflict(src, dest_dir / src.name, resolver)
                        if result == "cancelled":
                            break
                    else:
                        result = copy_file_with_conflict(src, dest_dir, resolver)
                        if result == "cancelled":
                            break
            except Exception as e:
                errors.append(f"{src.name}: {e}")

        if mode == "cut" and not resolver.cancelled:
            self.file_clipboard = None

        if errors:
            messagebox.showerror("Paste Errors", "\n".join(errors), parent=self)

        self.refresh_both()
        if len(sources) == 1 and not resolver.cancelled:
            self.active_pane.refresh(select_name=sources[0].name)

    def action_create_shortcut(self):
        """Create Windows .lnk shortcuts to selected items in the current folder."""
        if os.name != "nt":
            messagebox.showinfo("Create Shortcut", "Shortcuts are only supported on Windows.", parent=self)
            return
        if find_archive_root(self.active_pane.current_path):
            messagebox.showinfo("Archive Notice", "Cannot create shortcuts inside archives.", parent=self)
            return
        sources = self.active_pane.get_selected_paths()
        if not sources:
            return

        dest_dir = self.active_pane.current_path
        errors: list[str] = []
        created = 0
        for src in sources:
            try:
                base = src.name + ".lnk"
                lnk = dest_dir / base
                n = 1
                while lnk.exists():
                    lnk = dest_dir / f"{src.name} ({n}).lnk"
                    n += 1
                # Escape for PowerShell single-quoted strings
                lnk_ps = str(lnk).replace("'", "''")
                tgt_ps = str(src.resolve()).replace("'", "''")
                work_ps = str(src.parent.resolve() if src.is_file() else src.resolve()).replace("'", "''")
                ps = (
                    "$ws = New-Object -ComObject WScript.Shell; "
                    f"$s = $ws.CreateShortcut('{lnk_ps}'); "
                    f"$s.TargetPath = '{tgt_ps}'; "
                    f"$s.WorkingDirectory = '{work_ps}'; "
                    "$s.Save()"
                )
                subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps],
                    check=True,
                    capture_output=True,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
                )
                created += 1
            except Exception as e:
                errors.append(f"{src.name}: {e}")

        if errors:
            messagebox.showerror("Create Shortcut", "\n".join(errors), parent=self)
        if created:
            self.active_pane.refresh()
            if self.inactive_pane.current_path == self.active_pane.current_path:
                self.inactive_pane.refresh()

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
            raw = path.read_bytes()
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            try:
                from charset_normalizer import from_bytes

                content = str(from_bytes(raw).best())
            except Exception:
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
        if self.app_config.get("copy_verify_hash"):
            for src in sources:
                if src.is_file():
                    dst = target_dir / src.name
                    if dst.is_file() and not files_equal(src, dst):
                        errors.append(f"Verify failed: {src.name}")

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

    def action_delete(self, permanent: bool = False):
        """F8 / Delete: Recycle Bin; Shift+Del = permanent."""
        permanent = permanent or self._delete_permanent
        self._delete_permanent = False
        if find_archive_root(self.active_pane.current_path):
            messagebox.showinfo("Archive Notice", "Deleting items from archives is not supported.", parent=self)
            return
        sources = self.active_pane.get_selected_paths()
        if not sources:
            return

        listing = "\n".join(f"• {p.name}" for p in sources[:10])
        if len(sources) > 10:
            listing += f"\n... and {len(sources) - 10} more"
        mode = "permanently delete" if permanent else "move to Recycle Bin"
        confirm = messagebox.askyesno(
            "Confirm Delete (F8)",
            f"{mode.title()} {len(sources)} selected item(s)?\n\n{listing}",
            icon=messagebox.WARNING,
            parent=self,
        )
        if not confirm:
            return

        dlg = OperationProgressDialog(self, "Deleting…")
        errors: list[str] = []

        def worker():
            errors.extend(delete_paths(sources, permanent=permanent))
            self.after(0, lambda: self._finish_batch_delete(dlg, errors))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_batch_delete(self, dlg: OperationProgressDialog, errors: list[str]):
        dlg.destroy()
        if errors:
            messagebox.showerror("Delete Errors", "\n".join(errors), parent=self)
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
  - Line colors: pale red (changed), orange (deleted), green (added), gray (pad)
  - Within changed lines, differing words/parts are highlighted:
      red = removed, green = added, yellow = replaced
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
  Right-Click     Context menu for one or several selected/marked items
  Shift+F10 / Menu key   Same context menu via keyboard

[ CONTEXT MENU ]  (Right-Click / Shift+F10 — Explorer / TC / Far style)
  Open, Open with, View F3, Edit F4
  Cut Ctrl+X, Copy Ctrl+C, Paste Ctrl+V          — clipboard like Explorer
  Copy/Move to Other Panel F5/F6                 — Commander panel ops
  Delete, Rename, New Folder, Create Shortcut
  Compare by Content, Copy as Path, Copy Filename(s)
  Mark / Select All, Command Prompt, Show in Explorer, Properties
  Works with multi-select and marked items (☑)

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

    def _focus_active_filter(self):
        self.active_pane.filter_entry.focus_set()

    def toggle_show_hidden(self):
        cur = bool(self.app_config.get("show_hidden"))
        self.app_config.set("show_hidden", not cur)
        self.refresh_both()

    def toggle_quick_view(self):
        cur = bool(self.app_config.get("quick_view_enabled"))
        self.app_config.set("quick_view_enabled", not cur)
        self.active_pane._on_select_quick_view()
        self.inactive_pane._on_select_quick_view()

    def _rebuild_bookmarks_menu(self):
        self.bookmarks_menu.delete(0, tk.END)
        for i, path in enumerate(self.app_config.get("bookmarks") or []):
            self.bookmarks_menu.add_command(
                label=f"{i + 1}. {path}",
                command=lambda p=path: self.active_pane.navigate_to(Path(p)),
            )

    def action_bookmark_add(self):
        path = str(self.active_pane.current_path)
        books = list(self.app_config.get("bookmarks") or [])
        if path not in books:
            books.append(path)
            self.app_config.set("bookmarks", books)
        self._rebuild_bookmarks_menu()

    def action_bookmark_go(self, index: int):
        books = self.app_config.get("bookmarks") or []
        if 0 <= index < len(books):
            self.active_pane.navigate_to(Path(books[index]))

    def action_sync_dirs(self):
        show_sync_summary(self, self.active_pane.current_path, self.inactive_pane.current_path)

    def action_multirename(self):
        names = [p.name for p in self.active_pane.get_selected_paths()]
        if not names:
            return

        def apply(pattern: str):
            from pycommander.multirename import expand_rename

            for i, n in enumerate(names):
                src = self.active_pane.current_path / n
                new_name = expand_rename(n, pattern, i + 1)
                dst = src.parent / new_name
                if src != dst:
                    src.rename(dst)
            self.active_pane.refresh()

        show_multirename_dialog(self, names, apply)

    def action_search(self):
        root = self.active_pane.current_path

        def on_pick(p: Path | None):
            if p and p.parent.is_dir():
                self.active_pane.navigate_to(p.parent, select_name=p.name)

        show_search_dialog(self, root, on_pick)

    def action_duplicates(self):
        show_duplicates_dialog(self, self.active_pane.current_path)

    def action_create_zip(self):
        sources = self.active_pane.get_selected_paths()
        if not sources:
            return
        dest = filedialog.asksaveasfilename(
            parent=self, defaultextension=".zip", filetypes=[("ZIP", "*.zip")]
        )
        if not dest:
            return
        create_zip_from_selection(Path(dest), sources)
        self.active_pane.refresh()

    def _setup_watchdog(self, path: Path):
        if Observer is None or find_archive_root(path):
            return
        path_key = str(path)
        if path_key == self._watch_path and self._fs_observer is not None:
            return
        self._watch_path = path_key
        if self._fs_observer:
            try:
                self._fs_observer.stop()
                self._fs_observer.join(timeout=0.05)
            except Exception:
                pass
            self._fs_observer = None

        class _H(FileSystemEventHandler):
            def __init__(self, app_ref, pane_ref):
                self.app_ref = app_ref
                self.pane_ref = pane_ref

            def on_any_event(self, event):
                aid = self.app_ref._watch_refresh_after
                if aid:
                    try:
                        self.app_ref.after_cancel(aid)
                    except Exception:
                        pass
                self.app_ref._watch_refresh_after = self.app_ref.after(
                    1200, lambda: self.pane_ref.refresh(preserve_focus=True)
                )

        try:
            obs = Observer()
            obs.schedule(_H(self, self.active_pane), path_key, recursive=False)
            obs.daemon = True
            obs.start()
            self._fs_observer = obs
        except Exception as e:
            LOG.warning("Watchdog unavailable: %s", e)

    def _try_setup_dnd(self):
        if DND_FILES is None:
            return
        try:
            for pane in (self.left_pane, self.right_pane):
                pane.tree.drop_target_register(DND_FILES)
                pane.tree.dnd_bind(
                    "<<Drop>>",
                    lambda e, p=pane: self._on_drop_files(e, p),
                )
        except Exception as e:
            LOG.warning("Drag-and-drop disabled: %s", e)

    def _on_drop_files(self, event, target_pane: FilePane):
        raw = event.data
        paths = []
        for part in self.tk.splitlist(raw):
            paths.append(Path(part))
        if not paths:
            return
        dest = target_pane.current_path
        resolver = ConflictResolver(self)
        for src in paths:
            if src.is_dir():
                copy_dir_with_conflict(src, dest / src.name, resolver)
            elif src.is_file():
                copy_file_with_conflict(src, dest, resolver)
        target_pane.refresh()

    def action_about(self):
        from pycommander import __version__

        messagebox.showinfo(
            "About PyCommander",
            f"PyCommander {__version__}\n\n"
            "A dual-pane file manager inspired by Total Commander.",
            parent=self,
        )
