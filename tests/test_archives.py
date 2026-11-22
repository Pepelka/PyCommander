import zipfile
from pathlib import Path

from pycommander.archives import (
    find_archive_root,
    list_archive_entries,
    extract_archive_item,
    add_paths_to_zip,
)


def test_zip_list_and_extract(tmp_path):
    zpath = tmp_path / "t.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("folder/hi.txt", "data")
    inner = tmp_path / "t.zip" / "folder"
    assert find_archive_root(inner) is not None
    arch, rel = find_archive_root(inner)
    assert arch == zpath.resolve()
    entries = list_archive_entries(arch, rel)
    assert any(e["name"] == "hi.txt" for e in entries)
    out = tmp_path / "out"
    extract_archive_item(arch, f"{rel}/hi.txt".strip("/"), out, None)
    assert (out / "hi.txt").read_text(encoding="utf-8") == "data"


def test_add_paths_to_zip(tmp_path):
    f = tmp_path / "one.txt"
    f.write_text("1", encoding="utf-8")
    z = tmp_path / "out.zip"
    add_paths_to_zip(z, [f])
    with zipfile.ZipFile(z) as zf:
        assert "one.txt" in zf.namelist()