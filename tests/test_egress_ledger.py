"""Every request reports its database cost and adds it to the daily ledger."""

import socket
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from httpx2 import Client

from app.core.db import (
    Cost,
    _cost,
    _count_received,
    _start_received,
    received,
    start_request_cost,
)
from app.services import egress

SECRET = "egress-secret"


@pytest.fixture
def scheduler(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    monkeypatch.setenv("CRON_SECRET", SECRET)
    return {"Authorization": f"Bearer {SECRET}"}


def test_a_list_route_reports_its_cost(client: Client, seeded: dict[str, Any]) -> None:
    response = client.get(f"/events/{seeded['season_id']}/series")
    assert response.status_code == 200
    assert int(response.headers["X-DB-Statements"]) > 0
    assert int(response.headers["X-DB-Rows"]) > 0
    assert int(response.headers["X-Response-Bytes"]) == len(response.content)


def test_the_ledger_counts_every_call(
    client: Client, seeded: dict[str, Any], scheduler: dict[str, str]
) -> None:
    for _ in range(3):
        client.get(f"/events/{seeded['season_id']}/series")
    client.get("/users")
    client.get("/no/such/path")
    assert client.request("FOO", "/users").status_code == 405

    response = client.get("/jobs/egress", headers=scheduler)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    rows = {(row["route"], row["method"]): row for row in response.json()}
    assert set(rows) == {("/events/{event_id}/series", "GET"), ("/users", "GET")}
    series = rows[("/events/{event_id}/series", "GET")]
    assert series["calls"] == 3
    assert series["rows"] > 0
    assert series["bytes"] > 0
    assert rows[("/users", "GET")]["calls"] == 1

    # The read route itself is never recorded
    again = client.get("/jobs/egress", headers=scheduler).json()
    assert {row["route"] for row in again} == {"/events/{event_id}/series", "/users"}


def test_the_ledger_is_behind_the_scheduler_secret(
    client: Client, scheduler: dict[str, str]
) -> None:
    assert client.get("/jobs/egress").status_code == 401


def test_a_worker_thread_counts_toward_the_request(app: object) -> None:
    """The W3C sync runs its players in a thread pool; their statements are the request's."""
    from concurrent.futures import ThreadPoolExecutor

    from sqlalchemy import text

    from app.core.db import Session, start_request_cost, submit_in_context

    def read() -> None:
        with Session() as session:
            session.execute(text("SELECT 1")).all()

    cost = start_request_cost()
    with ThreadPoolExecutor(2) as pool:
        submit_in_context(pool, read).result()
        pool.submit(read).result()
    assert (cost.statements, cost.rows) == (1, 1)


@pytest.fixture
def tcp() -> Iterator[tuple[socket.socket, socket.socket]]:
    """A connected pair of TCP sockets on the loopback: (sender, receiver)."""
    with socket.create_server(("127.0.0.1", 0)) as server:
        receiver = socket.create_connection(server.getsockname())
        sender, _ = server.accept()
        with sender, receiver:
            yield sender, receiver


def take(receiver: socket.socket, sender: socket.socket, n: int) -> None:
    sender.sendall(b"x" * n)
    got = 0
    while got < n:
        got += len(receiver.recv(n - got))


@pytest.mark.skipif(not hasattr(socket, "TCP_INFO"), reason="TCP_INFO is Linux only")
def test_received_is_the_bytes_the_kernel_counted(
    tcp: tuple[socket.socket, socket.socket],
) -> None:
    sender, receiver = tcp
    assert received(receiver.fileno()) == 0
    take(receiver, sender, 12_345)
    assert received(receiver.fileno()) == 12_345
    # Reading the count leaves the socket open
    take(receiver, sender, 1)
    assert received(receiver.fileno()) == 12_346


@pytest.mark.skipif(not hasattr(socket, "TCP_INFO"), reason="TCP_INFO is Linux only")
def test_each_check_in_adds_what_arrived_since_the_last(
    tcp: tuple[socket.socket, socket.socket],
) -> None:
    sender, receiver = tcp
    conn = SimpleNamespace(
        closed=False, pgconn=SimpleNamespace(socket=receiver.fileno())
    )
    record = SimpleNamespace(info={})
    _start_received(conn, record)
    cost = start_request_cost()
    take(receiver, sender, 600)
    _count_received(conn, record)
    take(receiver, sender, 400)
    _count_received(conn, record)
    assert cost.db_bytes == 1_000
    # Outside a request the count moves on and nothing is added
    _cost.set(None)
    take(receiver, sender, 50)
    _count_received(conn, record)
    assert record.info["received"] == 1_050


def test_the_ledger_adds_the_measured_bytes_of_each_call(
    app: object, scheduler: dict[str, str], client: Client
) -> None:
    for _ in range(2):
        egress.record("/x", "GET", Cost(statements=2, rows=3, db_bytes=500), 10)
    row = next(
        r
        for r in client.get("/jobs/egress", headers=scheduler).json()
        if r["route"] == "/x"
    )
    assert (row["calls"], row["db_bytes"], row["bytes"]) == (2, 1_000, 20)


def test_an_invalidated_connection_checks_in_without_a_count() -> None:
    record = SimpleNamespace(info={"received": 5})
    cost = start_request_cost()
    _count_received(None, record)
    _count_received(SimpleNamespace(closed=True), record)
    assert (cost.db_bytes, record.info["received"]) == (0, 5)
