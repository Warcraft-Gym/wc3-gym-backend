"""The w3champions call always ends.

W3Champions is a third-party service. A call with no timeout holds its
thread until the socket closes, so the service must give one on every
request and must fail the same way as any other network error. The calls
share one connection pool, so the patch here is on the session class.

A refusal for rate is its own error: the sync stops instead of reporting
every player as broken.
"""

import pytest
import requests

from app.core.exceptions import W3CThrottledError
from app.services.w3c import REQUEST_TIMEOUT, W3CService


class FakeResponse:
    def __init__(
        self, status_code: int = 200, headers: dict[str, str] | None = None
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self.text = "refused"

    def json(self) -> dict[str, str]:
        return {"battleTag": "P1#1234"}


def answer(
    monkeypatch: pytest.MonkeyPatch, response: FakeResponse
) -> dict[str, object]:
    """The session answers this, and the call arguments come back for assertions."""
    sent: dict[str, object] = {}

    def fake_request(
        self: requests.Session, method: str, url: str, **kwargs: object
    ) -> FakeResponse:
        sent.update(kwargs)
        return response

    monkeypatch.setattr(requests.Session, "request", fake_request)
    return sent


def raise_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_request(
        self: requests.Session, method: str, url: str, **kwargs: object
    ) -> None:
        raise requests.exceptions.Timeout("read timed out")

    monkeypatch.setattr(requests.Session, "request", fake_request)


def test_the_request_carries_a_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """HARD GATE: no timeout parks the thread for as long as w3champions hangs."""
    sent = answer(monkeypatch, FakeResponse())

    body = W3CService().send_request(method="GET", url="https://example.test/p")

    assert body == {"battleTag": "P1#1234"}
    assert sent["timeout"] == REQUEST_TIMEOUT


def test_a_timeout_fails_like_any_other_network_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Timeout is a RequestException, so the one handler already covers it."""
    raise_timeout(monkeypatch)

    with pytest.raises(Exception, match="An exception occurred: read timed out"):
        W3CService().send_request(method="GET", url="https://example.test/p")


def test_the_player_check_answers_false_on_a_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Signup calls this. A hung w3champions must not hang the signup."""
    raise_timeout(monkeypatch)
    monkeypatch.setenv("W3C_URL", "https://example.test/api/players")

    assert W3CService().validate_player("P1#1234") is False


@pytest.mark.parametrize(
    "status,headers",
    [(429, {}), (503, {"Retry-After": "30"})],
)
def test_a_refusal_for_rate_is_a_throttle(
    monkeypatch: pytest.MonkeyPatch, status: int, headers: dict[str, str]
) -> None:
    answer(monkeypatch, FakeResponse(status_code=status, headers=headers))

    with pytest.raises(W3CThrottledError):
        W3CService().send_request(method="GET", url="https://example.test/p")


def test_a_503_without_retry_after_stays_an_ordinary_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the rate refusal stops a sync; every other status is one player's failure."""
    answer(monkeypatch, FakeResponse(status_code=503))

    with pytest.raises(Exception, match="status code 503") as failure:
        W3CService().send_request(method="GET", url="https://example.test/p")
    assert not isinstance(failure.value, W3CThrottledError)
