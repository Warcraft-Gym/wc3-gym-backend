"""The w3champions call always ends.

W3Champions is a third-party service. A call with no timeout holds its
thread until the socket closes, so the service must give one on every
request and must fail the same way as any other network error.
"""

import pytest
import requests

from app.services.w3c import REQUEST_TIMEOUT, W3CService


class FakeResponse:
    status_code = 200

    def json(self) -> dict[str, str]:
        return {"battleTag": "P1#1234"}


def test_the_request_carries_a_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """HARD GATE: no timeout parks the thread for as long as w3champions hangs."""
    sent: dict[str, object] = {}

    def fake_request(method: str, url: str, **kwargs: object) -> FakeResponse:
        sent.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr(requests, "request", fake_request)

    body = W3CService().send_request(method="GET", url="https://example.test/p")

    assert body == {"battleTag": "P1#1234"}
    assert sent["timeout"] == REQUEST_TIMEOUT


def test_a_timeout_fails_like_any_other_network_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Timeout is a RequestException, so the one handler already covers it."""

    def fake_request(method: str, url: str, **kwargs: object) -> None:
        raise requests.exceptions.Timeout("read timed out")

    monkeypatch.setattr(requests, "request", fake_request)

    with pytest.raises(Exception, match="An exception occurred: read timed out"):
        W3CService().send_request(method="GET", url="https://example.test/p")


def test_the_player_check_answers_false_on_a_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Signup calls this. A hung w3champions must not hang the signup."""

    def fake_request(method: str, url: str, **kwargs: object) -> None:
        raise requests.exceptions.Timeout("read timed out")

    monkeypatch.setattr(requests, "request", fake_request)
    monkeypatch.setenv("W3C_URL", "https://example.test/api/players")

    assert W3CService().validatePlayer("P1#1234") is False
