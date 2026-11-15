# PyCommander

A dual-pane file manager inspired by Total Commander, written in pure Python using only the standard library (Tkinter, `os`, `shutil`, `pathlib`, `zipfile`, `tarfile`, `difflib`).

## Features

- **Dual-pane layout** — left and right file panels, switch with Tab
- **Sortable columns** — Name, Ext, Size, Modified (click headers)
- **Function key toolbar** — F1–F10 with classic Commander shortcuts
- **File selection** — Insert (mark + move down), Space (toggle mark), Ctrl+A (all), Ctrl+D (deselect), `*` (invert)
- **F3 Lister** — text preview and hex+ASCII dump for binary files
- **F4 Editor** — built-in text editor with Ctrl+S save
- **F5 Copy** — with overwrite confirmation dialog (Overwrite / Overwrite All / Skip / Skip All / Cancel)
- **F6 Move/Rename** — with overwrite confirmation dialog
- **F7 MkDir** — create new directory
- **F8 Delete** — with confirmation
- **Archive browsing** — enter `.zip`, `.jar`, `.tar`, `.tgz`, `.tar.gz` as virtual folders; F5 extracts
- **Path history** — Alt+Left (back), Alt+Right (forward), Alt+Down / ▾ dropdown
- **Command history** — Up/Down arrows in command bar, dropdown list
- **Compare by Content** — Ctrl+Alt+C: side-by-side line diff with synchronized scrolling, F7/Shift+F7 to jump between differences
- **Shell integration** — F9 opens interactive terminal; command bar runs commands in background (non-blocking)
- **Drive selector** — Windows drive letters dropdown per pane
- **Cursor position preserved** after copy/move operations in both panes

## Requirements

- Python 3.10+ (uses `match` syntax and `str | None` type hints)
- No third-party packages needed

## Usage

```bash
python pycommander.py
```

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| F1 | Help |
| F2 | Rename |
| F3 | View / Lister |
| F4 | Edit |
| F5 | Copy |
| F6 | Move / Rename |
| F7 | Make Directory |
| F8 | Delete |
| F9 | Terminal |
| F10 | Quit |
| Tab | Switch active pane |
| Insert | Mark item and move cursor down |
| Space | Toggle mark |
| Ctrl+A | Select all |
| Ctrl+D | Deselect all |
| `*` | Invert selection |
| Alt+Left | Navigate back |
| Alt+Right | Navigate forward |
| Alt+Down | Show path history dropdown |
| Alt+Enter | File properties |
| Ctrl+Alt+C | Compare files by content |
| Ctrl+R | Refresh both panes |
| BackSpace | Go up one directory |
