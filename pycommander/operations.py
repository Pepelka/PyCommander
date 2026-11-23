"""File copy/move with conflict handling."""
import os
import stat
import shutil
from pathlib import Path

from pycommander.paths import get_path_info
from pycommander.conflict import ConflictResolver

def copy_file_with_conflict(src: Path, dst: Path, resolver: ConflictResolver) -> str:
    """
    Copy a single file from src to dst respecting conflict resolution.
    Returns: 'copied', 'skipped', or 'cancelled'.
    """
    if resolver.cancelled:
        return "cancelled"

    resolver.report_file(src)
    target_file = dst / src.name if dst.is_dir() else dst

    try:
        if src.resolve() == target_file.resolve():
            return "skipped"
    except Exception:
        pass

    if target_file.exists():
        src_info = get_path_info(src)
        dst_info = get_path_info(target_file)
        action = resolver.resolve(src_info, dst_info, target_file)
        if action == "cancel":
            return "cancelled"
        elif action == "skip":
            return "skipped"

        # Overwrite
        try:
            os.chmod(target_file, stat.S_IWRITE | stat.S_IREAD)
        except Exception:
            pass
        shutil.copy2(src, target_file)
        return "copied"
    else:
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target_file)
        return "copied"


def copy_dir_with_conflict(src_dir: Path, dst_dir: Path, resolver: ConflictResolver) -> str:
    """
    Recursively copy directory contents respecting conflict resolution.
    Returns: 'copied', 'skipped', or 'cancelled'.
    """
    if resolver.cancelled:
        return "cancelled"

    dst_dir.mkdir(parents=True, exist_ok=True)
    for entry in src_dir.iterdir():
        if resolver.cancelled:
            return "cancelled"
        resolver.report_file(entry)
        target = dst_dir / entry.name
        if entry.is_dir():
            res = copy_dir_with_conflict(entry, target, resolver)
            if res == "cancelled":
                return "cancelled"
        else:
            res = copy_file_with_conflict(entry, target, resolver)
            if res == "cancelled":
                return "cancelled"
    return "copied"


def move_with_conflict(src: Path, dst: Path, resolver: ConflictResolver) -> str:
    """
    Move src to dst respecting conflict resolution.
    Returns: 'moved', 'skipped', or 'cancelled'.
    """
    if resolver.cancelled:
        return "cancelled"

    resolver.report_file(src)
    target = dst / src.name if dst.is_dir() and not (dst.exists() and src.is_dir() and dst.name == src.name) else dst

    try:
        if src.resolve() == target.resolve():
            return "skipped"
    except Exception:
        pass

    if target.exists():
        src_info = get_path_info(src)
        dst_info = get_path_info(target)
        action = resolver.resolve(src_info, dst_info, target)
        if action == "cancel":
            return "cancelled"
        elif action == "skip":
            return "skipped"

        # Overwrite
        if target.is_dir() and src.is_dir():
            res = copy_dir_with_conflict(src, target, resolver)
            if res == "cancelled":
                return "cancelled"
            shutil.rmtree(src, ignore_errors=True)
            return "moved"
        else:
            try:
                os.chmod(target, stat.S_IWRITE | stat.S_IREAD)
                if target.is_file():
                    target.unlink()
                elif target.is_dir():
                    shutil.rmtree(target, ignore_errors=True)
            except Exception:
                pass
            shutil.move(str(src), str(target))
            return "moved"
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(target))
        return "moved"
