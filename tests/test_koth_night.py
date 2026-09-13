"""A KOTH night run through the API: open it, sign up, play, close it.

A night is one event of the KOTH league: three brackets, one stage of format
koth and one chain of best-of-one series per bracket. Every step here is the
call an admin or Nightbot makes, so the assertions read the shapes the run
page draws rather than the rows the module writes.
"""

from typing import Any

from httpx2 import Client

from app.core.db import Session
from app.models.base import ident
from app.models.enums import Race
from app.models.user import User
from app.models.w3c_stats import W3CStats
from tests.test_stage_engine import score, stage_series

TOKEN = "test-nightbot-token"
NIGHT = "2026-09-14T19:00:00Z"
LATER = "2026-09-21T19:00:00Z"


def enrol(tag: str, mmr: int, race: Race = Race.HU, season: int = 20) -> int:
    """One player with a battle tag and one W3C rating the signup reads."""
    with Session.begin() as session:
        user = User(
            name=tag.split("#")[0],
            battleTag=tag,
            discordTag="",
            discordId="",
            race=race,
        )
        session.add(user)
        session.flush()
        session.add(
            W3CStats(
                user_id=ident(user), race=race, wc3_season=season, games=50, mmr=mmr
            )
        )
        return ident(user)


def open_night(
    client: Client,
    headers: dict[str, str],
    starts_at: str = NIGHT,
    **body: list[int] | str,
) -> dict[str, Any]:
    resp = client.post(
        "/koth/nights", json={"starts_at": starts_at, **body}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def sign_up(client: Client, tag: str, twitch: str, race: str | None = None) -> Any:  # noqa: ANN401
    params = {"token": TOKEN, "twitch": twitch, "battletag": tag}
    if race:
        params["race"] = race
    return client.get("/koth/signup", params=params)


def entrants(client: Client, event: int) -> list[dict[str, Any]]:
    resp = client.get(f"/events/{event}/entrants")
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_a_night_is_one_event_of_the_koth_league(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """One event, one koth stage best of one, three brackets strongest first."""
    night = open_night(client, auth_headers)

    assert night["kind"] == "koth"
    assert night["league_short_name"] == "KOTH"
    assert night["signup_policy"] == "anyone"
    assert night["published"] is True
    assert night["name"] == "14 September 2026"
    assert [(row["format"], row["best_of"]) for row in night["stages"]] == [("koth", 1)]
    assert [
        (row["position"], row["name"], row["lower_bound"]) for row in night["divisions"]
    ] == [(1, "Bracket 3", 1600), (2, "Bracket 2", 1450), (3, "Bracket 1", 0)]


def test_a_night_takes_the_bounds_of_the_night_before(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The bounds are named once; the next night reads them off the last one."""
    open_night(client, auth_headers, lower_bounds=[0, 1500, 1800])
    second = open_night(client, auth_headers, starts_at=LATER)

    assert [row["lower_bound"] for row in second["divisions"]] == [1800, 1500, 0]


def test_a_twitch_signup_lands_in_the_bracket_its_rating_cuts(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The chat line names the bracket and the rating behind the signup."""
    night = open_night(client, auth_headers)
    enrol("Mid#1000", 1500)

    resp = sign_up(client, "Mid#1000", "streamer", "human")

    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "success": True,
        "message": "streamer signed up for Bracket 2 (1500 MMR)",
    }
    rows = entrants(client, night["id"])
    assert [(row["race"], row["mmr"]) for row in rows] == [("HU", 1500)]


def test_a_second_signup_replaces_the_race_and_the_bracket(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """One entrant per player per night: the second command replaces the first."""
    night = open_night(client, auth_headers)
    user_id = enrol("Two#2000", 1400)
    with Session.begin() as session:
        session.add(
            W3CStats(user_id=user_id, race=Race.NE, wc3_season=20, games=50, mmr=1700)
        )

    first = sign_up(client, "Two#2000", "streamer", "human")
    assert first.json()["message"] == "streamer signed up for Bracket 1 (1400 MMR)"

    second = sign_up(client, "Two#2000", "streamer", "nightelf")

    assert second.status_code == 200, second.text
    assert second.json()["message"] == "streamer signed up for Bracket 3 (1700 MMR)"
    rows = entrants(client, night["id"])
    assert [(row["race"], row["mmr"]) for row in rows] == [("NE", 1700)]


def test_an_unknown_race_answers_400(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    open_night(client, auth_headers)
    resp = sign_up(client, "Any#1", "streamer", "gnome")
    assert resp.status_code == 400
    assert "Valid options" in resp.json()["error"]


def test_a_signup_with_no_night_open_is_refused(
    client: Client, seeded: dict[str, Any]
) -> None:
    resp = sign_up(client, "Any#1", "streamer", "human")
    assert resp.status_code == 400
    assert resp.json()["error"] == "No KOTH night is open"


def test_two_signups_in_one_bracket_draw_the_throne_series(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The chain is drawn once every bracket that holds entrants holds two."""
    night = open_night(client, auth_headers)
    enrol("A#1", 1400)
    enrol("B#2", 1300)
    sign_up(client, "A#1", "a", "human")
    sign_up(client, "B#2", "b", "human")

    body = stage_series(client, night["id"], night["stages"][0]["id"])

    assert len(body["series"]) == 1
    assert [row["number"] for row in body["rounds"]] == [1]


def test_the_king_of_the_night_before_takes_seed_one(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The crown is carried, not stored: last night's winner opens tonight."""
    first = open_night(client, auth_headers)
    enrol("King#1", 1300)
    enrol("Rival#2", 1400)
    sign_up(client, "King#1", "king", "human")
    sign_up(client, "Rival#2", "rival", "human")
    # MMR seeds the rival first, so the throne goes to the weaker player
    row = stage_series(client, first["id"], first["stages"][0]["id"])["series"][0]
    assert score(client, auth_headers, row["id"], 0, 1).status_code == 200

    second = open_night(client, auth_headers, starts_at=LATER)
    sign_up(client, "Rival#2", "rival", "human")
    sign_up(client, "King#1", "king", "human")

    rows = entrants(client, second["id"])
    assert {row["user"]["battleTag"]: row["seed"] for row in rows} == {
        "King#1": 1,
        "Rival#2": 2,
    }
    assert {row["seed_source"] for row in rows} == {"manual"}


def test_closing_a_night_deletes_the_series_nobody_played(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """One scored series stands; the pending end of every chain goes.

    The night then reads finished once the phase counts the series of an
    event through their round, which the FOML run pins as the gap it has
    today (tests/test_foml_league.py:374).
    """
    night = open_night(client, auth_headers)
    # Bracket 3 waits for its pair, so bracket 1 fills to a chain of two
    for tag, mmr in (
        ("C1#1", 1400),
        ("T1#4", 1700),
        ("C2#2", 1300),
        ("C3#3", 1200),
        ("T2#5", 1650),
    ):
        enrol(tag, mmr)
        sign_up(client, tag, tag.split("#")[0], "human")

    stage = night["stages"][0]["id"]
    rows = stage_series(client, night["id"], stage)["series"]
    assert len(rows) == 3
    played = next(row for row in rows if row["player2_id"] is not None)
    assert score(client, auth_headers, played["id"], 1, 0).status_code == 200

    closed = client.post(f"/koth/nights/{night['id']}/close", headers=auth_headers)

    assert closed.status_code == 200, closed.text
    assert closed.json()["signups_open"] is False
    left = stage_series(client, night["id"], stage)["series"]
    assert [row["id"] for row in left] == [played["id"]]
