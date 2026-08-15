"""Every error answers the same envelope, and a 500 exposes nothing.

The router's own errors (unknown path, wrong method) carry the envelope
too, so a client can always read the error field. An unhandled exception
answers a fixed body: what went wrong goes to the log with the
traceback, not to the client.
"""

from typing import Never

import pytest
from httpx2 import Client

from app.services.maps import MapService


def test_an_unknown_path_answers_the_envelope(client: Client) -> None:
    resp = client.get("/no-such-route")
    assert resp.status_code == 404
    assert resp.json() == {"error": "Not Found"}


def test_a_wrong_method_answers_the_envelope(client: Client) -> None:
    resp = client.delete("/maps")
    assert resp.status_code == 405
    assert resp.json() == {"error": "Method Not Allowed"}
    assert resp.headers["allow"]


def test_a_bug_answers_a_fixed_body(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(self: MapService) -> Never:
        raise RuntimeError("an internal detail the client must not see")

    monkeypatch.setattr(MapService, "getAll", broken)
    resp = client.get("/maps")
    assert resp.status_code == 500
    assert resp.json() == {"error": "Internal Server Error"}
