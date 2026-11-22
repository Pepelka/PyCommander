from pathlib import Path
from unittest.mock import MagicMock

from pycommander.conflict import ConflictResolver


class _FakeDialog:
    def __init__(self, result):
        self.result = result

    def wait_window(self):
        pass


def test_conflict_resolver_skip_all(monkeypatch):
    parent = MagicMock()
    resolver = ConflictResolver(parent)
    resolver.skip_all = True
    assert resolver.resolve({}, {}, Path("x")) == "skip"


def test_conflict_resolver_overwrite_all():
    parent = MagicMock()
    resolver = ConflictResolver(parent)
    resolver.overwrite_all = True
    assert resolver.resolve({}, {}, Path("x")) == "overwrite"