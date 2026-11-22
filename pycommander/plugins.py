"""Load optional user plugins from config plugins directory."""
from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

from pycommander.config import config_dir

LOG = logging.getLogger("pycommander.plugins")


def plugins_folder() -> Path:
    d = config_dir() / "plugins"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_plugins(app) -> list:
    """Import *.py plugins exposing register(app)."""
    loaded = []
    for py in sorted(plugins_folder().glob("*.py")):
        if py.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"pycommander_plugin_{py.stem}", py)
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, "register"):
                mod.register(app)
                loaded.append(py.name)
                LOG.info("Loaded plugin %s", py.name)
        except Exception as e:
            LOG.warning("Plugin %s failed: %s", py.name, e)
    return loaded