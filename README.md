# PyCommander

Dual-pane file manager inspired by Total Commander (package layout `pycommander/`).

## Requirements

- Python 3.10+
- See [requirements.txt](requirements.txt) and [requirements-dev.txt](requirements-dev.txt)

## Run

```bash
pip install -r requirements.txt
python -m pycommander
```

Or: `python pycommander.py` / `python run.py`

## Tests

```bash
pip install -r requirements-dev.txt
pytest tests -q --cov=pycommander
```

## Features (summary)

- Dual pane, marks, context menu, Cut/Copy/Paste, F5/F6 panel ops
- Compare by content with inline highlights
- Archives: zip/tar browse; 7z read; zip create/add
- Recycle Bin delete (Shift+Del permanent)
- Quick filter, hidden files toggle, bookmarks, sync summary, multi-rename, search, duplicates
- Progress/cancel hooks, watchdog refresh, optional plugins, drag-and-drop (tkinterdnd2)

## Manual test matrix

| Area | Check |
|------|-------|
| Context menu | Open, Open with, Cut/Copy/Paste, F5/F6 |
| Delete | F8 → Recycle Bin; Shift+Del → permanent |
| Filter | Ctrl+F in pane filter row |
| Bookmarks | Commands → Add; Ctrl+1..9 |
| DnD | Drop files between panes (Windows) |

## Packaging

```bash
pip install pyinstaller
pyinstaller PyCommander.spec
```