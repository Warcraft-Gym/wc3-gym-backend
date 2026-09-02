"""What the typed request bodies must keep accepting.

The bodies these routes take are Pydantic models rather than plain dicts, so
the tolerances the handlers used to apply by hand now live in the models. The
three that no other test pins are here: the bot's numbers-or-text fields, the
key a body may leave out to keep the stored value, and the key it may leave
out to mean an empty list.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx2 import Client

BOT_TOKEN = "bot-client-token"
from tests.test_fantasy_locks import schedule


@pytest.fixture(autouse=True)
def empty_store() -> Iterator[dict[str, dict[str, Any]]]:
    """The store is process-global, so empty it around each test."""
    from app.api.routes.public import _token_store

    _token_store.clear()
    yield _token_store
    _token_store.clear()


@pytest.mark.parametrize("season_id,ttl", [("3", "30"), (3, 30)])
def test_the_access_helper_takes_the_season_and_ttl_as_text_or_numbers(
    client: Client,
    monkeypatch: pytest.MonkeyPatch,
    season_id: str | int,
    ttl: str | int,
) -> None:
    """The bot sends whatever its config holds, so both shapes must mint."""
    monkeypatch.setenv("BOT_CLIENT_TOKEN", BOT_TOKEN)

    resp = client.post(
        "/public-access-helper",
        json={
            "client_token": BOT_TOKEN,
            "discord_id": "1",
            "discord_tag": "p1",
            "season_id": season_id,
            "access_type": "signup",
            "ttl_minutes": ttl,
        },
    )

    assert resp.status_code == 200, resp.text
    token = resp.json()["token"]
    assert client.get(f"/public-token/{token}").json()["season_id"] == "3"


def test_a_bet_update_without_the_points_keeps_the_stored_points(
    client: Client, seeded: dict[str, Any], empty_store: dict[str, dict[str, Any]]
) -> None:
    """A key the body leaves out is not a null; the bet keeps what it held."""
    bet = client.get("/fantasy/bets").json()[0]
    schedule(
        seeded["series_played_id"], datetime.now(UTC) + timedelta(days=1)
    )  # the series is still open
    empty_store["t"] = {
        "discord_id": "1",
        "discord_tag": "p1",
        "season_id": None,
        "access_type": "fantasy",
        "expires_at": datetime.now(UTC) + timedelta(minutes=5),
    }

    resp = client.put(f"/fantasy-bet/{bet['id']}", json={"token": "t"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["bet_points"] == bet["bet_points"]
    assert resp.json()["winner_id"] == bet["winner_id"]


def test_captains_left_out_of_the_body_clears_them(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    """A missing captain_ids reads as an empty list, as the dict body did."""
    path = f"/teams/{seeded['team_a_id']}/seasons/{seeded['season_id']}/captains"

    resp = client.put(path, json={}, headers=auth_headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["captains_by_season"] == {}
