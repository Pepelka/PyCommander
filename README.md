# PyCommander

Dual-pane file manager inspired by Total Commander (`pycommander/` package).

## Requirements

- Python 3.10+
- [requirements.txt](requirements.txt) · dev: [requirements-dev.txt](requirements-dev.txt)

## Run

```bash
pip install -r requirements.txt
python -m pycommander
```

Also: `python pycommander.py` or `python run.py`

## Tests

```bash
pip install -r requirements-dev.txt
pytest tests -q --cov=pycommander
```

## Features (summary)

| Area | Highlights |
|------|------------|
| Panes | Tab switch, marks, quick filter row, large-dir cap, path history |
| Files | F5/F6 panels, Cut/Copy/Paste, Recycle Bin (Shift+Del permanent) |
| UI | Context menu (Explorer/TC style), Open with, bookmarks Ctrl+1–9 |
| View | Hidden files, Quick View strip, optional folder watcher |
| Tools | Compare (inline word diff), sync summary, multi-rename, file search, duplicates, ZIP create |
| Archives | Browse zip/tar; read .7z; extract (F5) |
| Lister/Editor | Encoding, line numbers, find/replace, hex view, go to line |

Press **F1** in the app for the full shortcut list.

## Keys (quick reference)

| Key | Action |
|-----|--------|
| F1 | Help |
| F2–F8 | Rename, View, Edit, Copy, Move, MkDir, Delete |
| F9 / F10 | Terminal, Quit |
| Tab | Active pane |
| Ctrl+F | Pane filter (list); in F3/F4 window: Find |
| Ctrl+Alt+C | Compare by content |
| Shift+Del | Permanent delete |

## Manual smoke checks

| Area | Check |
|------|-------|
| Context | Open with, Cut/Copy/Paste, F5/F6 |
| Delete | F8 → Recycle Bin; Shift+Del → permanent |
| Lister | Ctrl+F, Enter next match, hex toggle |
| Panes | Tab switch should be instant |

## Packaging

```bash
pip install pyinstaller
pyinstaller PyCommander.spec
```

(User `.spec` is gitignored; copy from docs or generate locally.)