"""Run copy/move/delete batches on the UI thread with progress + cancel."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pycommander.conflict import ConflictResolver
from pycommander.dialogs import OperationProgressDialog


def run_main_thread_batch(
    parent,
    title: str,
    items: list[Any],
    process_item: Callable[[Any, ConflictResolver, list[str]], None],
    on_complete: Callable[[list[str], bool], None],
    *,
    item_label: Callable[[Any], str] | None = None,
) -> None:
    """
    Process items one-by-one via parent.after so conflict dialogs stay modal.

    on_complete(errors, was_cancelled)
    """
    if not items:
        on_complete([], False)
        return

    dlg = OperationProgressDialog(parent, title)
    resolver = ConflictResolver(dlg)
    resolver.progress_dialog = dlg
    errors: list[str] = []
    state = {"index": 0}

    def on_cancel():
        resolver.cancelled = True

    dlg.set_on_cancel(on_cancel)

    def label_for(item: Any) -> str:
        if item_label:
            return item_label(item)
        return getattr(item, "name", str(item))

    def step():
        if dlg.cancelled:
            resolver.cancelled = True
        idx = state["index"]
        if idx >= len(items) or resolver.cancelled:
            cancelled = dlg.cancelled or resolver.cancelled
            dlg.close()
            on_complete(errors, cancelled)
            return

        item = items[idx]
        name = label_for(item)
        dlg.update_progress(idx + 1, len(items), name)
        try:
            process_item(item, resolver, errors)
        except Exception as e:
            errors.append(f"{name}: {e}")

        state["index"] = idx + 1
        parent.after(1, step)

    parent.after(1, step)