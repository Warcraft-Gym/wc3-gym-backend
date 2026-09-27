"""A person's Discord account is served only to a logged-in player read.

Every other shape keeps it in memory for the Discord cards and leaves it off
the wire, so an open read never carries it.
"""

from collections.abc import Callable
from typing import Any

from app.core.db import Session
from app.models.enums import Race
from app.models.relationships import DBUserSeasonSignup
from app.services.series import SeriesService
from app.services.series_cards import reminder_card
from tests.conftest import Client

DISCORD = ("discordId", "discordTag")


def bare(row: dict[str, Any]) -> bool:
    return not any(key in row for key in DISCORD)


def test_an_anonymous_player_read_has_no_discord_account(
    client: Client, seeded: dict[str, Any]
) -> None:
    resp = client.get(f"/users/{seeded['player_ids'][0]}")
    assert resp.status_code == 200
    assert bare(resp.json())
    assert resp.headers["cache-control"] == (
        "public, s-maxage=120, stale-while-revalidate=600"
    )


def test_a_logged_in_player_read_has_the_discord_account(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
) -> None:
    resp = client.get(f"/users/{seeded['player_ids'][0]}", headers=member("2"))
    assert resp.status_code == 200
    body = resp.json()
    assert (body["discordId"], body["discordTag"]) == ("1", "p1")
    assert "public" not in resp.headers.get("cache-control", "")


def test_a_series_player_signup_row_and_career_row_have_none(
    client: Client, seeded: dict[str, Any]
) -> None:
    with Session() as session:
        session.add(
            DBUserSeasonSignup(
                user_id=seeded["player_ids"][0],
                season_id=seeded["season_id"],
                race=Race.HU,
            )
        )
        session.commit()
    series = client.get(f"/series/{seeded['series_played_id']}").json()
    assert bare(series["player1"]) and bare(series["player2"])
    (signup,) = client.get(f"/events/{seeded['season_id']}/signups").json()
    assert bare(signup)
    career = client.get("/stats/career").json()
    assert career and all(bare(row["user"]) for row in career)
    teams = client.get(f"/events/{seeded['season_id']}/teams").json()
    roster = [p for t in teams for p in t["player_by_season"][str(seeded["season_id"])]]
    assert roster and all(bare(p) for p in roster)


def test_a_cast_has_no_discord_id_and_the_reminder_still_tags(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
) -> None:
    series_id = seeded["series_open_id"]
    resp = client.post(
        f"/series/{series_id}/casts",
        json={"channel_url": "twitch.tv/gnlcaster"},
        headers=member("3"),
    )
    assert resp.status_code == 201, resp.text
    assert "discord_id" not in resp.json()[0]
    assert all(
        "discord_id" not in cast
        for cast in client.get(f"/series/{series_id}").json()["casts"]
    )

    # The cards read the in-memory shape, which keeps the ids
    series = SeriesService().get(series_id)
    content = reminder_card(series)["content"]
    assert content.startswith("<@2> <@") and "<@3>" in content


def test_the_user_list_and_search_serve_the_discord_account_to_an_admin_only(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    member: Callable[..., dict[str, str]],
) -> None:
    def rows(headers: dict[str, str]) -> list[list[dict[str, Any]]]:
        listed = client.get("/users", headers=headers)
        found = client.post("/users/search?query=name == P1", headers=headers)
        assert listed.status_code == 200 and found.status_code == 200, found.text
        assert found.json()
        return [listed.json(), found.json()]

    for answer in rows(auth_headers):
        p1 = next(row for row in answer if row["name"] == "P1")
        assert (p1["discordId"], p1["discordTag"]) == ("1", "p1")
    for headers in (member("2"), {}):
        for answer in rows(headers):
            assert all(bare(row) for row in answer)
