"""Pure selection/mark resolution for file panes."""
import os


def resolve_selection_paths(
    current_path,
    marked_items: set[str],
    tree_selection: list[str],
    tree_children_in_order: list[str],
    focus: str | None,
    prefer_marks: bool = True,
):
    """
    Return list of Path for operations.

    Mirrors FilePane.get_selected_paths without Tk dependencies.
    """
    from pathlib import Path

    if prefer_marks and marked_items:
        ordered = [
            iid
            for iid in tree_children_in_order
            if iid in marked_items and iid != ".."
        ]
        return [current_path / name for name in ordered]

    sel = [s for s in tree_selection if s != ".."]
    if not sel and focus and focus != "..":
        sel = [focus]
    return [current_path / name for name in sel]


def filter_entries(entries: list[dict], query: str) -> list[dict]:
    """Client-side quick filter by name or extension (case-insensitive)."""
    q = query.strip().lower()
    if not q:
        return entries
    out = []
    for e in entries:
        name = e.get("name", "").lower()
        ext = e.get("ext", "").lower()
        if q in name or q in ext:
            out.append(e)
    return out


def is_hidden_entry(entry_name: str, entry_path, show_hidden: bool) -> bool:
    if show_hidden:
        return False
    if entry_name in (".", ".."):
        return True
    if entry_name.startswith("."):
        return True
    if os.name == "nt":
        try:
            import stat as st

            attrs = entry_path.stat().st_file_attributes
            if attrs & st.FILE_ATTRIBUTE_HIDDEN:
                return True
        except (OSError, AttributeError):
            pass
    return False