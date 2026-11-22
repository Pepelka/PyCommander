from pathlib import Path


def test_plugin_loader(tmp_path, monkeypatch):
    from pycommander import config as cfg_mod
    from pycommander import plugins

    plug_dir = tmp_path / "plugins"
    plug_dir.mkdir()
    (plug_dir / "ex.py").write_text(
        "def register(app):\n    app._test_plugin = True\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(plugins, "plugins_folder", lambda: plug_dir)
    app = type("A", (), {})()
    loaded = plugins.load_plugins(app)
    assert "ex.py" in loaded
    assert app._test_plugin is True