"""Background batch operations with cancel support."""
from __future__ import annotations

import threading
from typing import Callable


class BatchCancel:
  def __init__(self) -> None:
    self._event = threading.Event()

  def cancel(self) -> None:
    self._event.set()

  @property
  def cancelled(self) -> bool:
    return self._event.is_set()

  def clear(self) -> None:
    self._event.clear()


def run_batch(
    items: list,
    worker: Callable[[object, BatchCancel], None],
    on_progress: Callable[[int, int, object], None] | None = None,
    on_done: Callable[[], None] | None = None,
) -> BatchCancel:
    """Run worker(item, cancel) for each item in a background thread."""
    cancel = BatchCancel()
    total = len(items)

    def runner():
        for i, item in enumerate(items):
            if cancel.cancelled:
                break
            worker(item, cancel)
            if on_progress:
                on_progress(i + 1, total, item)
        if on_done:
            on_done()

    threading.Thread(target=runner, daemon=True).start()
    return cancel