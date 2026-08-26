"""Two sync routes run at the same time.

The sync routes run in the server's thread pool. This test holds one
request inside the pool and sends a second one; both must meet. A pool of
one thread would make the second request wait behind the first, and the
meeting would time out.
"""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_two_sync_requests_run_at_the_same_time(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import deps

    meet = threading.Barrier(2, timeout=5)

    def wait_for_the_other(**kwargs: object) -> list[object]:
        meet.wait()  # raises BrokenBarrierError when the second request never arrives
        return []

    monkeypatch.setattr(deps.season_service, "get_all", wait_for_the_other)

    # One client in one context, so both requests share one event loop and
    # one thread pool, as they do in the server.
    with TestClient(app) as client, ThreadPoolExecutor(2) as pool:
        answers = list(pool.map(lambda _: client.get("/seasons"), range(2)))

    assert [a.status_code for a in answers] == [200, 200]
    assert meet.broken is False
