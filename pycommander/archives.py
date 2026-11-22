"""Archive virtual filesystem helpers."""
import os
import stat
import datetime
import zipfile
import tarfile
from pathlib import Path

from pycommander.paths import get_path_info

ARCHIVE_EXTENSIONS = (
    ".zip", ".jar", ".war", ".whl",
    ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz",
    ".7z",
)

try:
    import py7zr
except ImportError:  # pragma: no cover
    py7zr = None  # type: ignore


def is_archive_file(path: Path) -> bool:
    """Check if the given path is a supported archive file."""
    try:
        if not path.is_file():
            return False
        name = path.name.lower()
        if any(name.endswith(ext) for ext in ARCHIVE_EXTENSIONS):
            if zipfile.is_zipfile(str(path)) or tarfile.is_tarfile(str(path)):
                return True
            if name.endswith(".7z") and py7zr is not None:
                try:
                    with py7zr.SevenZipFile(path, mode="r"):
                        return True
                except Exception:
                    return False
        return False
    except OSError:
        return False


def find_archive_root(path: Path) -> tuple[Path, str] | None:
    """
    Check if `path` is an archive file or points inside an archive.
    Returns (archive_file_path, internal_relpath) or None.
    """
    cur = path
    sub_parts = []
    while True:
        try:
            if cur.is_file() and is_archive_file(cur):
                rel = "/".join(reversed(sub_parts))
                return (cur.resolve(), rel)
        except OSError:
            pass
        if cur.parent == cur:
            break
        sub_parts.append(cur.name)
        cur = cur.parent
    return None


def list_archive_entries(archive_path: Path, relpath: str = "") -> list[dict]:
    """List direct children inside an archive at `relpath`."""
    relpath = relpath.strip("/").replace("\\", "/")
    entries: dict[str, dict] = {}

    if zipfile.is_zipfile(str(archive_path)):
        with zipfile.ZipFile(archive_path, "r") as zf:
            for info in zf.infolist():
                fn = info.filename.strip("/").replace("\\", "/")
                if not fn:
                    continue
                if relpath:
                    if not (fn == relpath or fn.startswith(relpath + "/")):
                        continue
                    if fn == relpath:
                        continue
                    sub = fn[len(relpath) + 1 :]
                else:
                    sub = fn

                parts = sub.split("/")
                item_name = parts[0]
                is_dir = len(parts) > 1 or info.is_dir()
                try:
                    mtime = datetime.datetime(*info.date_time).timestamp()
                except Exception:
                    mtime = 0

                if item_name not in entries or (is_dir and not entries[item_name]["is_dir"]):
                    entries[item_name] = {
                        "name": item_name,
                        "is_dir": is_dir,
                        "size": 0 if is_dir else info.file_size,
                        "mtime": mtime,
                        "is_archive": False,
                    }
    elif tarfile.is_tarfile(str(archive_path)):
        with tarfile.open(archive_path, "r:*") as tf:
            for m in tf.getmembers():
                fn = m.name.lstrip("./").strip("/").replace("\\", "/")
                if not fn:
                    continue
                if relpath:
                    if not (fn == relpath or fn.startswith(relpath + "/")):
                        continue
                    if fn == relpath:
                        continue
                    sub = fn[len(relpath) + 1 :]
                else:
                    sub = fn

                parts = sub.split("/")
                item_name = parts[0]
                is_dir = len(parts) > 1 or m.isdir()
                if item_name not in entries or (is_dir and not entries[item_name]["is_dir"]):
                    entries[item_name] = {
                        "name": item_name,
                        "is_dir": is_dir,
                        "size": 0 if is_dir else m.size,
                        "mtime": m.mtime,
                        "is_archive": False,
                    }
    elif archive_path.name.lower().endswith(".7z"):
        return list_7z_entries(archive_path, relpath)
    return list(entries.values())


def read_archive_file(archive_path: Path, relpath: str) -> bytes:
    """Read full raw bytes of an entry inside an archive."""
    relpath = relpath.strip("/").replace("\\", "/")
    if zipfile.is_zipfile(str(archive_path)):
        with zipfile.ZipFile(archive_path, "r") as zf:
            return zf.read(relpath)
    elif tarfile.is_tarfile(str(archive_path)):
        with tarfile.open(archive_path, "r:*") as tf:
            f = tf.extractfile(relpath)
            if f is None:
                raise FileNotFoundError(f"Not a regular file in archive: {relpath}")
            return f.read()
    raise ValueError(f"Unsupported archive format: {archive_path}")


def extract_archive_item(archive_path: Path, relpath: str, dest_dir: Path, resolver: "ConflictResolver | None" = None) -> bool:
    """Extract an archive file or directory into `dest_dir` with conflict resolution."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    relpath = relpath.strip("/").replace("\\", "/")

    if zipfile.is_zipfile(str(archive_path)):
        with zipfile.ZipFile(archive_path, "r") as zf:
            matching = [info for info in zf.infolist() if info.filename.strip("/").replace("\\", "/") == relpath]
            if matching and not matching[0].is_dir():
                out_path = dest_dir / Path(relpath).name
                if out_path.exists():
                    if resolver:
                        mtime = (
                            datetime.datetime(*matching[0].date_time).timestamp()
                            if matching[0].date_time
                            else 0
                        )
                        src_info = {
                            "name": out_path.name,
                            "path": f"{archive_path.name}/{relpath}",
                            "size": matching[0].file_size,
                            "mtime": mtime,
                            "is_dir": False,
                        }
                        dst_info = get_path_info(out_path)
                        act = resolver.resolve(src_info, dst_info, out_path)
                        if act == "cancel":
                            return False
                        elif act == "skip":
                            return True
                    try:
                        os.chmod(out_path, stat.S_IWRITE | stat.S_IREAD)
                    except Exception:
                        pass
                with zf.open(matching[0]) as source, open(out_path, "wb") as target:
                    target.write(source.read())
                return True

            prefix = relpath + "/" if relpath else ""
            base_folder = Path(relpath).name if relpath else ""
            for info in zf.infolist():
                if resolver and resolver.cancelled:
                    return False
                fn = info.filename.strip("/").replace("\\", "/")
                if prefix and not fn.startswith(prefix):
                    continue
                sub_rel = fn[len(prefix) :] if prefix else fn
                if not sub_rel:
                    continue
                target_path = dest_dir / base_folder / Path(sub_rel) if base_folder else dest_dir / Path(sub_rel)
                if info.is_dir():
                    target_path.mkdir(parents=True, exist_ok=True)
                else:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    if target_path.exists():
                        if resolver:
                            mtime = (
                                datetime.datetime(*info.date_time).timestamp()
                                if info.date_time
                                else 0
                            )
                            src_info = {
                                "name": target_path.name,
                                "path": f"{archive_path.name}/{info.filename}",
                                "size": info.file_size,
                                "mtime": mtime,
                                "is_dir": False,
                            }
                            dst_info = get_path_info(target_path)
                            act = resolver.resolve(src_info, dst_info, target_path)
                            if act == "cancel":
                                return False
                            elif act == "skip":
                                continue
                        try:
                            os.chmod(target_path, stat.S_IWRITE | stat.S_IREAD)
                        except Exception:
                            pass
                    with zf.open(info) as src, open(target_path, "wb") as dst:
                        dst.write(src.read())
            return True
    elif tarfile.is_tarfile(str(archive_path)):
        with tarfile.open(archive_path, "r:*") as tf:
            matching = [m for m in tf.getmembers() if m.name.lstrip("./").strip("/").replace("\\", "/") == relpath]
            if matching and not matching[0].isdir():
                out_path = dest_dir / Path(relpath).name
                if out_path.exists():
                    if resolver:
                        src_info = {
                            "name": out_path.name,
                            "path": f"{archive_path.name}/{relpath}",
                            "size": matching[0].size,
                            "mtime": matching[0].mtime,
                            "is_dir": False,
                        }
                        dst_info = get_path_info(out_path)
                        act = resolver.resolve(src_info, dst_info, out_path)
                        if act == "cancel":
                            return False
                        elif act == "skip":
                            return True
                    try:
                        os.chmod(out_path, stat.S_IWRITE | stat.S_IREAD)
                    except Exception:
                        pass
                f = tf.extractfile(matching[0])
                if f:
                    with open(out_path, "wb") as target:
                        target.write(f.read())
                return True

            prefix = relpath + "/" if relpath else ""
            base_folder = Path(relpath).name if relpath else ""
            for m in tf.getmembers():
                if resolver and resolver.cancelled:
                    return False
                fn = m.name.lstrip("./").strip("/").replace("\\", "/")
                if prefix and not fn.startswith(prefix):
                    continue
                sub_rel = fn[len(prefix) :] if prefix else fn
                if not sub_rel:
                    continue
                target_path = dest_dir / base_folder / Path(sub_rel) if base_folder else dest_dir / Path(sub_rel)
                if m.isdir():
                    target_path.mkdir(parents=True, exist_ok=True)
                else:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    if target_path.exists():
                        if resolver:
                            src_info = {
                                "name": target_path.name,
                                "path": f"{archive_path.name}/{m.name}",
                                "size": m.size,
                                "mtime": m.mtime,
                                "is_dir": False,
                            }
                            dst_info = get_path_info(target_path)
                            act = resolver.resolve(src_info, dst_info, target_path)
                            if act == "cancel":
                                return False
                            elif act == "skip":
                                continue
                        try:
                            os.chmod(target_path, stat.S_IWRITE | stat.S_IREAD)
                        except Exception:
                            pass
                    f = tf.extractfile(m)
                    if f:
                        with open(target_path, "wb") as dst:
                            dst.write(f.read())
            return True
    return False


def list_7z_entries(archive_path: Path, relpath: str = "") -> list[dict]:
    if py7zr is None:
        return []
    relpath = relpath.strip("/").replace("\\", "/")
    entries: dict[str, dict] = {}
    with py7zr.SevenZipFile(archive_path, mode="r") as z:
        names = z.getnames()
        for fn in names:
            fn = fn.strip("/").replace("\\", "/")
            if not fn:
                continue
            if relpath:
                if not (fn == relpath or fn.startswith(relpath + "/")):
                    continue
                if fn == relpath:
                    continue
                sub = fn[len(relpath) + 1 :]
            else:
                sub = fn
            parts = sub.split("/")
            item = parts[0]
            is_dir = len(parts) > 1 or fn.endswith("/")
            if item not in entries:
                entries[item] = {
                    "name": item,
                    "is_dir": is_dir,
                    "size": 0,
                    "mtime": 0,
                    "is_archive": False,
                }
    return list(entries.values())


def add_paths_to_zip(zip_path: Path, sources: list[Path], arc_prefix: str = "") -> None:
    """Append files/folders to a zip (create if missing)."""
    arc_prefix = arc_prefix.strip("/").replace("\\", "/")
    mode = "a" if zip_path.exists() else "w"
    with zipfile.ZipFile(zip_path, mode, compression=zipfile.ZIP_DEFLATED) as zf:
        for src in sources:
            if src.is_dir():
                for p in src.rglob("*"):
                    if p.is_file():
                        rel = p.relative_to(src)
                        arcname = f"{arc_prefix}/{rel}".strip("/") if arc_prefix else str(rel)
                        zf.write(p, arcname.replace("\\", "/"))
            elif src.is_file():
                arcname = f"{arc_prefix}/{src.name}".strip("/") if arc_prefix else src.name
                zf.write(src, arcname.replace("\\", "/"))


def create_zip_from_selection(dest_zip: Path, sources: list[Path]) -> None:
    add_paths_to_zip(dest_zip, sources)
