"""The w3champions base URL and season resolve without configuration.

A fresh database holds no settings rows. The base URL falls back to a
default, and the season comes from w3champions itself, so the config page
starts working instead of blank.
"""

import pytest
import requests

from app.services.settings import SettingsService
from app.services.w3c import DEFAULT_BASE_URL, W3CService
from tests.conftest import Client


def test_the_base_url_falls_back_to_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("W3C_URL", raising=False)

    assert W3CService().base_url() == DEFAULT_BASE_URL


@pytest.mark.parametrize(
    "stored",
    [
        "https://example.test/api",
        "https://example.test/api/",
        "https://example.test/api/players",
        "https://example.test/api/players/",
    ],
)
def test_a_stored_players_endpoint_still_reads_as_the_base(
    monkeypatch: pytest.MonkeyPatch, stored: str
) -> None:
    """Configuration written before the split named the players endpoint."""
    monkeypatch.setenv("W3C_URL", stored)

    assert W3CService().base_url() == "https://example.test/api"


def test_the_player_check_asks_for_the_players_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: dict[str, str] = {}

    class FakeResponse:
        status_code = 200

        def json(self) -> dict[str, str]:
            return {"battleTag": "P1#1234"}

    def fake_request(method: str, url: str, **kwargs: object) -> FakeResponse:
        asked["url"] = url
        return FakeResponse()

    monkeypatch.setattr(requests, "request", fake_request)
    monkeypatch.setenv("W3C_URL", "https://example.test/api")

    assert W3CService().validatePlayer("P1#1234") is True
    assert asked["url"] == "https://example.test/api/players/P1%231234"


def test_the_season_comes_from_w3champions_when_none_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """w3champions lists newest first, so the season is the largest id."""

    class FakeResponse:
        status_code = 200

        def json(self) -> list[dict[str, int]]:
            return [{"id": 25}, {"id": 24}, {"id": 23}]

    monkeypatch.setattr(requests, "request", lambda *a, **k: FakeResponse())
    monkeypatch.setenv("W3C_URL", "https://example.test/api")

    assert W3CService().current_season() == 25


def test_a_configured_season_wins_over_w3champions() -> None:
    """A season typed on the config page is a deliberate choice."""
    settings = SettingsService()
    settings.update_setting("current_wc3_season", "18")

    assert W3CService(settings_app_service=settings).current_season() == 18


def test_a_missing_setting_does_not_raise() -> None:
    """An absent row used to raise NotFoundError before any fallback ran."""
    assert W3CService(settings_app_service=SettingsService()).base_url() != ""


def test_the_config_route_reports_the_url_in_use(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeResponse:
        status_code = 200

        def json(self) -> list[dict[str, int]]:
            return [{"id": 25}, {"id": 24}]

    monkeypatch.setattr(requests, "request", lambda *a, **k: FakeResponse())
    monkeypatch.setenv("W3C_URL", "https://example.test/api")

    body = client.get("/config/w3c").json()

    assert body["w3c_url"] == "https://example.test/api"
    assert body["current_season"] == 25


def test_the_config_route_survives_w3champions_being_down(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The page must still load when the third party does not answer."""

    def fake_request(*args: object, **kwargs: object) -> None:
        raise requests.exceptions.Timeout("read timed out")

    monkeypatch.setattr(requests, "request", fake_request)

    body = client.get("/config/w3c").json()

    assert body["current_season"] is None
