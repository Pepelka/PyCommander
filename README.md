# PyCommander

Dual-pane file manager for Windows (and other platforms with Tk), inspired by Total Commander. The UI lives in the [`pycommander/`](pycommander/) package (**0.2.0**).

## Requirements

- **Python 3.10+**
- Runtime deps: [requirements.txt](requirements.txt)
- Dev/test: [requirements-dev.txt](requirements-dev.txt)

## Install and run

```bash
pip install -r requirements.txt
python -m pycommander
```

Optional editable install:

```bash
pip install -e ".[windows]"
pycommander
```

Legacy launchers: `python pycommander.py` or `python run.py`.

Settings are stored under `%APPDATA%\PyCommander\config.json` on Windows, or `~/.config/pycommander/config.json` elsewhere.

## Tests

```bash
pip install -r requirements-dev.txt
pytest tests -q
# with coverage:
pytest tests -q --cov=pycommander
```

## Features

| Area | Highlights |
|------|------------|
| **Panes** | Left/right panes, Tab to switch; path bar, back/forward, bookmarks (Ctrl+1–9); quick filter (Ctrl+F on list); marks vs selection for operations |
| **Session** | Last left/right paths saved on exit (F10) and restored on start, including paths **inside** ZIP/TAR archives |
| **Files** | F5 copy panel, F6 move, Cut/Copy/Paste, drag-and-drop into panes (tkinterdnd2) |
| **Progress** | Copy, move, delete, paste, and drop show a **progress bar** with **Cancel** (per-item stop; overwrite prompts stay usable) |
| **Delete** | F8 / Delete → Recycle Bin (`send2trash`); **Shift+Del** → permanent delete |
| **Conflicts** | Overwrite / skip / skip all / cancel when a target already exists |
| **Archives** | Browse `.zip`, `.jar`, `.tar*`, `.7z` (7z read); F3 view inside archives; F5 copies the archive **file** on disk, extracts **members** when you are inside an archive |
| **UI** | Explorer / Total Commander–style context menu, **Open with** (Windows), optional Quick View strip |
| **View** | Hidden files toggle; optional folder watcher (debounced refresh, large dirs capped at 5000 entries) |
| **Lister / editor (F3 / F4)** | Encoding, line numbers, wrap, hex view, find/replace, go to line (F3 search uses the text window, not the pane filter) |
| **Tools** | Compare by content (inline word diff), sync summary, multi-rename, file search, duplicate finder, create ZIP from selection |
| **Shell** | F9 command line, integrated terminal shortcut; Windows shell clipboard for file Cut/Copy when available |
| **Plugins** | Optional user scripts from the plugins folder (see in-app / loader stub) |

Press **F1** in the app for the full shortcut and archive help text.

## Keys (quick reference)

| Key | Action |
|-----|--------|
| F1 | Help |
| F2–F8 | Rename, View, Edit, Copy, Move, MkDir, Delete |
| F9 / F10 | Terminal, Quit (saves session paths) |
| Tab | Active pane |
| Ctrl+F | Pane quick filter; in F3/F4 window: Find |
| Ctrl+X/C/V | Cut / Copy / Paste |
| Ctrl+Alt+C | Compare by content |
| Shift+Del | Permanent delete |
| Alt+←/→ | History back / forward |

## Manual smoke checks

| Area | Check |
|------|-------|
| Copy | F5 copies a `.zip` as one file; open archive → F5 extracts selected members |
| Progress | Multi-file F5/F6/F8 shows centered progress dialog; Cancel stops after current item |
| Session | Open a folder and an archive path in each pane → F10 → restart → paths restored |
| Delete | F8 → Recycle Bin; Shift+Del → permanent |
| Lister | F3 → Ctrl+F, F3/Shift+F3 next/prev match, hex toggle |
| Panes | Tab switch feels instant (no watchdog block on UI thread) |

## Packaging

```bash
pip install pyinstaller
pyinstaller PyCommander.spec
```

The `.spec` file is not in the repo by default; generate or copy locally as needed.