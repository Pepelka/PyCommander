import zipfile

from pathlib import Path

from pycommander.session_paths import is_navigable_path, session_start_path, normalize_stored_path


def test_archive_inner_path_navigable(tmp_path):
    z = tmp_path / "bundle.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("inner/readme.txt", "hi")
    inner = tmp_path / "bundle.zip" / "inner"
    assert is_navigable_path(inner)
    restored = session_start_path(str(inner), tmp_path)
    assert restored == normalize_stored_path(inner)


def test_invalid_falls_back_to_default(tmp_path):
    bad = tmp_path / "nope" / "nope"
    assert session_start_path(str(bad), tmp_path) == tmp_path