"""Persistent application settings."""
from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path

DEFAULTS: dict = {
    "show_hidden": False,
    "prefer_marks_for_ops": True,
    "column_widths": {},
    "last_left_path": "",
    "last_right_path": "",
    "bookmarks": [],
    "open_with_recent": [],
    "copy_verify_hash": False,
    "quick_view_enabled": False,
    "refresh_cap": 5000,
    "compare_ignore_ws": False,
    "compare_ignore_case": False,
}


def config_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home())) / "PyCommander"
    else:
        base = Path.home() / ".config" / "pycommander"
    base.mkdir(parents=True, exist_ok=True)
    return base


def config_path() -> Path:
    return config_dir() / "settings.json"


class AppConfig:
    def __init__(self) -> None:
        self.data: dict = deepcopy(DEFAULTS)
        self._save_timer = None
        self.load()

    def load(self) -> None:
        path = config_path()
        if not path.is_file():
            return
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self.data.update(loaded)
        except (OSError, json.JSONDecodeError):
            pass

    def save(self) -> None:
        try:
            config_path().write_text(
                json.dumps(self.data, indent=2), encoding="utf-8"
            )
        except OSError:
            pass

    def get(self, key: str, default=None):
        return self.data.get(key, default if default is not None else DEFAULTS.get(key))

    def set(self, key: str, value, *, persist: bool = True) -> None:
        if self.data.get(key) == value:
            return
        self.data[key] = value
        if persist:
            self.schedule_save()

    def schedule_save(self, delay_ms: int = 400) -> None:
        """Debounce disk writes (avoids lag on every pane click)."""
        import threading

        if self._save_timer is not None:
            self._save_timer.cancel()

        def _do_save():
            self._save_timer = None
            self.save()

        self._save_timer = threading.Timer(delay_ms / 1000.0, _do_save)
        self._save_timer.daemon = True
        self._save_timer.start()

    def flush(self) -> None:
        if self._save_timer is not None:
            self._save_timer.cancel()
            self._save_timer = None
        self.save()