from pycommander.progress import BatchCancel, run_batch


def test_batch_cancel_stops_worker():
    cancel = BatchCancel()
    seen = []

    def worker(item, c):
        seen.append(item)
        if item == 2:
            c.cancel()

    run_batch([1, 2, 3], worker)
    import time

    time.sleep(0.2)
    assert 2 in seen