from pycommander.config import AppConfig, DEFAULTS


def test_config_defaults():
    c = AppConfig()
    assert c.get("show_hidden") == DEFAULTS["show_hidden"]


def test_config_roundtrip(tmp_path, monkeypatch):
    from pycommander import config as cfg_mod

    monkeypatch.setattr(cfg_mod, "config_dir", lambda: tmp_path)
    c = AppConfig()
    c.set("bookmarks", ["/tmp/a"])
    c.flush()
    c2 = AppConfig()
    assert c2.get("bookmarks") == ["/tmp/a"]