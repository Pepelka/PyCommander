import os
import time

import pytest


@pytest.mark.timeout(30)
def test_scan_many_names(tmp_path):
    for i in range(2000):
        (tmp_path / f"f_{i}.txt").write_text("x", encoding="utf-8")
    t0 = time.perf_counter()
    count = sum(1 for _ in os.scandir(tmp_path))
    elapsed = time.perf_counter() - t0
    assert count == 2000
    assert elapsed < 15.0