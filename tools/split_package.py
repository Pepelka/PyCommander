"""One-off script to split monolithic pycommander.py into package modules."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
lines = (ROOT / "pycommander.py").read_text(encoding="utf-8").splitlines(keepends=True)


def chunk(start: int, end: int) -> str:
    return "".join(lines[start - 1 : end])


pkg = ROOT / "pycommander"
pkg.mkdir(exist_ok=True)

(pkg / "__init__.py").write_text(
    '"""PyCommander dual-pane file manager."""\n__version__ = "0.2.0"\n',
    encoding="utf-8",
)

(pkg / "paths.py").write_text(
    '"""Path metadata helpers."""\nimport datetime\nfrom pathlib import Path\n\n'
    + chunk(360, 378),
    encoding="utf-8",
)

(pkg / "utils.py").write_text(
    '"""Shared utilities."""\nimport os\nimport string\nimport datetime\nfrom pathlib import Path\n\n'
    + chunk(317, 357)
    + "\n\n"
    + chunk(298, 314),
    encoding="utf-8",
)

# Patch utils to import archives lazily in get_file_bytes
utils = (pkg / "utils.py").read_text(encoding="utf-8")
utils = utils.replace(
    "def get_file_bytes(path: Path) -> bytes:",
    'def get_file_bytes(path: Path) -> bytes:\n    from pycommander.archives import find_archive_root, read_archive_file',
)
(pkg / "utils.py").write_text(utils, encoding="utf-8")

archives_body = chunk(24, 295).replace("get_path_info", "get_path_info")
(pkg / "archives.py").write_text(
    '"""Archive virtual filesystem helpers."""\nimport os\nimport stat\nimport datetime\nimport zipfile\nimport tarfile\nfrom pathlib import Path\n\nfrom pycommander.paths import get_path_info\n\n'
    + archives_body,
    encoding="utf-8",
)

(pkg / "conflict.py").write_text(
    '"""Overwrite confirmation UI and conflict resolver."""\nimport tkinter as tk\nfrom tkinter import ttk\nfrom pathlib import Path\n\nfrom pycommander.utils import format_size, format_datetime\nfrom pycommander.paths import get_path_info\n\n'
    + chunk(381, 601),
    encoding="utf-8",
)

(pkg / "operations.py").write_text(
    '"""File copy/move with conflict handling."""\nimport os\nimport stat\nimport shutil\nfrom pathlib import Path\n\nfrom pycommander.paths import get_path_info\nfrom pycommander.conflict import ConflictResolver\n\n'
    + chunk(604, 712),
    encoding="utf-8",
)

(pkg / "pane.py").write_text(
    '"""Single file browser pane."""\n'
    + chunk(7, 21)
    + "\n\nfrom pycommander.utils import format_size, format_datetime, get_available_drives, get_file_bytes, get_file_text\n"
    + "from pycommander.archives import is_archive_file, find_archive_root, list_archive_entries\n"
    + "from pycommander.paths import get_path_info\n\n"
    + chunk(715, 1645),
    encoding="utf-8",
)

(pkg / "compare_win.py").write_text(
    '"""Compare by content window."""\n'
    + chunk(7, 21)
    + "\n\nfrom pycommander.utils import format_size, get_file_text\n\n"
    + chunk(1647, 2014),
    encoding="utf-8",
)

(pkg / "app.py").write_text(
    '"""Main application window."""\n'
    + chunk(7, 21)
    + """
from pycommander.archives import find_archive_root, list_archive_entries, extract_archive_item, is_archive_file
from pycommander.utils import format_size, get_file_bytes, get_file_text
from pycommander.paths import get_path_info
from pycommander.conflict import ConflictResolver
from pycommander.operations import copy_file_with_conflict, copy_dir_with_conflict, move_with_conflict
from pycommander.pane import FilePane
from pycommander.compare_win import FileCompareWindow

"""
    + chunk(2016, 3077),
    encoding="utf-8",
)

(pkg / "__main__.py").write_text(
    '"""python -m pycommander entry point."""\nfrom pycommander.app import TotalCommanderApp\n\n\ndef main():\n    app = TotalCommanderApp()\n    app.mainloop()\n\n\nif __name__ == "__main__":\n    main()\n',
    encoding="utf-8",
)

# Shim at root
(ROOT / "run.py").write_text(
    '#!/usr/bin/env python3\n"""Launcher for PyCommander (use python -m pycommander)."""\nfrom pycommander.__main__ import main\n\nif __name__ == "__main__":\n    main()\n',
    encoding="utf-8",
)

print("Split complete:", pkg)