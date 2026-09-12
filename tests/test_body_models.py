"""What the typed request bodies must keep accepting.

The bodies these routes take are Pydantic models rather than plain dicts, so
the tolerances the handlers used to apply by hand now live in the models. The
two that no other test pins are here: the key a body may leave out to keep
the stored value, and the key it may leave out to mean an empty list.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from httpx2 import Client

from tests.test_fantasy_locks import schedule, score


def test_a_bet_update_without_the_points_keeps_the_stored_points(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    """A key the body leaves out is not a null; the bet keeps what it held."""
    bet = client.get("/fantasy/bets").json()[0]
    # Unplayed and set later, the series is open again and its bets with it
    score(seeded["series_played_id"], None, None)
    schedule(seeded["series_played_id"], datetime.now(UTC) + timedelta(days=1))

    resp = client.put(f"/fantasy-bet/{bet['id']}", json={}, headers=member())

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
