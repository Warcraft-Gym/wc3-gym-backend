"""A KOTH night run through the API: open it, sign up, play, close it.

A night is one event of the KOTH league: three brackets, one stage of format
koth and one chain of best-of-one series per bracket. Every step here is the
call an admin or Nightbot makes, so the assertions read the shapes the run
page draws rather than the rows the module writes.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from httpx2 import Client

from app.core.db import Session
from app.core.exceptions import ExternalServiceError, W3CThrottledError
from app.models.base import ident
from app.models.enums import EventKind, Race
from app.models.user import User
from app.models.w3c_stats import W3CStats
from app.services.koth import legacy
from app.services.w3c import W3CService
from tests.test_event_entrants import Member
from tests.test_event_entrants import sign_up as sign_up_to_event
from tests.test_events import add_event
from tests.test_koth import silent_w3c, unplaced
from tests.test_stage_engine import open_chain, score, stage_series

TOKEN = "test-nightbot-token"
NIGHT = "2026-09-14T19:00:00Z"
LATER = "2026-09-21T19:00:00Z"
# The site door reads the event phase, which shuts on a night already over
TONIGHT = f"{datetime.now(tz=UTC).date():%Y-%m-%d}T19:00:00Z"


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


def brackets_of(client: Client, event: int) -> list[int]:
    """The divisions the entrants of the night hold, in signup order."""
    held = [row["division_id"] for row in entrants(client, event)]
    return list(dict.fromkeys(row for row in held if row is not None))


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


def test_a_second_race_enters_beside_the_first(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """One row per race: each race sits in the bracket its own rating cuts."""
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
    assert sorted((row["race"], row["mmr"]) for row in rows) == [
        ("HU", 1400),
        ("NE", 1700),
    ]
    assert len({row["division_id"] for row in rows}) == 2


def test_the_same_race_twice_writes_one_row(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A repeated command reopens the row of that race and adds none."""
    night = open_night(client, auth_headers)
    enrol("Same#1000", 1500)

    assert sign_up(client, "Same#1000", "same", "human").status_code == 200
    second = sign_up(client, "Same#1000", "same", "human")

    assert second.status_code == 200, second.text
    rows = entrants(client, night["id"])
    assert [(row["race"], row["mmr"]) for row in rows] == [("HU", 1500)]


def test_two_races_of_one_player_stand_in_one_bracket(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """Both rows stand in the bracket their ratings cut, each with its own place."""
    night = open_night(client, auth_headers)
    both = enrol("Both#1001", 1500)
    with Session.begin() as session:
        session.add(
            W3CStats(user_id=both, race=Race.NE, wc3_season=20, games=50, mmr=1550)
        )
    enrol("Rival#1002", 1520)
    sign_up(client, "Both#1001", "both", "human")
    sign_up(client, "Both#1001", "both", "nightelf")
    sign_up(client, "Rival#1002", "rival", "human")

    rows = entrants(client, night["id"])
    assert sorted(row["race"] for row in rows) == ["HU", "HU", "NE"]
    assert len({row["division_id"] for row in rows}) == 1
    assert sorted(row["seed"] for row in rows) == [1, 2, 3]


def test_a_leave_takes_the_race_it_names_and_every_race_when_it_names_none(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """`!koth leave hu` withdraws that race; `!koth leave` withdraws them all."""
    night = open_night(client, auth_headers)
    user_id = enrol("Two#3000", 1400)
    with Session.begin() as session:
        session.add(
            W3CStats(user_id=user_id, race=Race.NE, wc3_season=20, games=50, mmr=1700)
        )
    sign_up(client, "Two#3000", "two", "human")
    sign_up(client, "Two#3000", "two", "nightelf")

    legacy.withdraw("Two#3000", "human")

    left = {row["race"]: row["withdrawn_at"] for row in entrants(client, night["id"])}
    assert left["HU"] is not None
    assert left["NE"] is None

    legacy.withdraw("Two#3000")

    rows = entrants(client, night["id"])
    assert all(row["withdrawn_at"] is not None for row in rows)


def test_an_event_that_takes_one_entry_refuses_a_second_race(
    client: Client, seeded: dict[str, Any], member: Member
) -> None:
    """A cup leaves the switch off, so the player keeps his one row."""
    cup = add_event(kind=EventKind.cup)
    player = member("1")
    assert sign_up_to_event(client, cup, player, race="HU").status_code == 201

    second = sign_up_to_event(client, cup, player, race="NE")

    assert second.status_code == 400, second.text
    assert second.json()["error"] == "This entrant is already signed up"


def test_an_unknown_race_answers_400(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    open_night(client, auth_headers)
    resp = sign_up(client, "Any#1001", "streamer", "gnome")
    assert resp.status_code == 400
    assert "Valid options" in resp.json()["error"]


def test_a_signup_with_no_night_open_is_refused(
    client: Client, seeded: dict[str, Any]
) -> None:
    resp = sign_up(client, "Any#1001", "streamer", "human")
    assert resp.status_code == 400
    assert resp.json()["error"] == "No KOTH night is open"


def test_a_koth_write_refuses_an_id_from_another_kind_of_event(
    client: Client,
    auth_headers: dict[str, str],
    seeded: dict[str, Any],
    member: Member,
) -> None:
    """The old routes take a bare id, so each one checks the kind behind it."""
    cup = add_event(kind=EventKind.cup)
    entrant_id = sign_up_to_event(client, cup, member("1")).json()["id"]

    bracket = client.put(
        f"/koth/signups/{entrant_id}/bracket",
        json={"bracket": 2},
        headers=auth_headers,
    )
    scored = client.put(
        f"/koth/matches/{seeded['series_open_id']}/result",
        json={"winner_team_number": 1},
        headers=auth_headers,
    )
    dropped = client.delete(
        f"/koth/matches/{seeded['series_open_id']}", headers=auth_headers
    )

    assert bracket.status_code == 404, bracket.text
    assert scored.status_code == 404, scored.text
    assert dropped.status_code == 404, dropped.text


def test_ten_signups_draw_no_series_and_stand_in_the_line_they_came_in(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A KOTH night pairs by hand, so a signup writes its row and nothing else."""
    night = open_night(client, auth_headers)
    for number in range(10):
        tag = f"P{number}#1{number:03d}"
        enrol(tag, 1300 + number)
        assert sign_up(client, tag, f"p{number}", "human").status_code == 200

    body = stage_series(client, night["id"], night["stages"][0]["id"])

    assert body["series"] == []
    rows = entrants(client, night["id"])
    assert [row["seed"] for row in rows] == list(range(1, 11))


def test_the_generate_call_is_refused_on_a_koth_stage(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """Nothing draws a KOTH night: the admin makes every series during it."""
    night = open_night(client, auth_headers)
    stage = night["stages"][0]["id"]
    for tag, mmr in (("A#1001", 1400), ("B#1002", 1300)):
        enrol(tag, mmr)
        sign_up(client, tag, tag.split("#")[0], "human")

    resp = client.post(
        f"/events/{night['id']}/stages/{stage}/generate", headers=auth_headers
    )

    assert resp.status_code == 400, resp.text
    assert "paired by its admin" in resp.json()["error"]


def test_a_signup_with_no_rating_is_accepted_unplaced(
    client: Client,
    auth_headers: dict[str, str],
    seeded: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W3Champions knows nobody by that tag: the row stands for the admin."""
    silent_w3c(monkeypatch)
    night = open_night(client, auth_headers)

    resp = sign_up(client, "Ghost#9999", "ghost", "human")

    assert resp.status_code == 200, resp.text
    assert resp.json()["message"] == (
        "ghost is signed up; W3Champions gave no rating for Ghost#9999 yet,"
        " the admin places you"
    )
    rows = entrants(client, night["id"])
    assert rows[0]["division_id"] is None
    assert rows[0]["manual_placement"] is False
    assert rows[0]["seed"] is None


def test_the_site_answer_says_unplaced_in_the_row_it_returns(
    client: Client,
    auth_headers: dict[str, str],
    seeded: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dialog reads the outcome off the row: no division is unplaced."""
    silent_w3c(monkeypatch)
    night = open_night(client, auth_headers, starts_at=TONIGHT)

    resp = sign_up_to_event(client, night["id"], battle_tag="Ghost#9999", race="HU")

    assert resp.status_code == 201, resp.text
    assert resp.json()["division_id"] is None
    assert resp.json()["seed"] is None
    assert resp.json()["mmr"] is None
    assert resp.json()["manual_placement"] is False


def test_a_slow_or_throttled_w3c_still_takes_the_signup(
    client: Client,
    auth_headers: dict[str, str],
    seeded: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sync that never answers refuses nobody; the row waits unplaced."""
    night = open_night(client, auth_headers)
    monkeypatch.setattr(W3CService, "current_season", lambda self: 20)

    def refuse(
        self: W3CService, bnet_name: str, season_override: int | None = None
    ) -> list[Any]:
        raise W3CThrottledError("W3Champions throttled the sync")

    monkeypatch.setattr(W3CService, "get_player_stats", refuse)
    throttled = sign_up(client, "Slow#9001", "slow", "human")

    def timeout(
        self: W3CService, bnet_name: str, season_override: int | None = None
    ) -> list[Any]:
        raise ExternalServiceError("An exception occurred: timed out")

    monkeypatch.setattr(W3CService, "get_player_stats", timeout)
    late = sign_up(client, "Late#9002", "late", "human")

    assert throttled.status_code == 200, throttled.text
    assert late.status_code == 200, late.text
    assert unplaced(client, night["id"]) == ["Slow#9001", "Late#9002"]


def test_one_rated_tag_lands_in_the_same_bracket_through_every_door(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """Chat, the site and the admin write one row each, all in Bracket 2."""
    night = open_night(client, auth_headers, starts_at=TONIGHT)
    for tag in ("Chat#1001", "Site#1002", "Hand#1003"):
        enrol(tag, 1500)
    sign_up(client, "Chat#1001", "chat", "human")
    site = sign_up_to_event(client, night["id"], battle_tag="Site#1002", race="HU")
    hand = client.post(
        f"/events/{night['id']}/entrants/admin",
        json={"battle_tag": "Hand#1003", "race": "HU"},
        headers=auth_headers,
    )

    assert site.status_code == 201, site.text
    assert hand.status_code == 201, hand.text
    rows = entrants(client, night["id"])
    assert len({row["division_id"] for row in rows}) == 1
    assert [(row["user"]["battleTag"], row["seed"]) for row in rows] == [
        ("Chat#1001", 1),
        ("Site#1002", 2),
        ("Hand#1003", 3),
    ]


def test_a_bad_battle_tag_is_refused_at_every_door(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A tag that is not shaped like one writes no player and no row."""
    night = open_night(client, auth_headers, starts_at=TONIGHT)

    chat = sign_up(client, "Typo", "typo", "human")
    site = sign_up_to_event(client, night["id"], battle_tag="Typo#12", race="HU")
    hand = client.post(
        f"/events/{night['id']}/entrants/admin",
        json={"battle_tag": "Typo", "race": "HU"},
        headers=auth_headers,
    )

    for resp in (chat, site, hand):
        assert resp.status_code == 400, resp.text
        assert "Name#1234" in resp.json()["error"]
    assert entrants(client, night["id"]) == []


def test_a_late_signup_stands_last_and_moves_no_other_row(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The queue is the seed, so a late row takes the end of its bracket."""
    night = open_night(client, auth_headers)
    for tag, mmr in (("A#1001", 1400), ("B#1002", 1300), ("Top#1003", 1700)):
        enrol(tag, mmr)
        sign_up(client, tag, tag.split("#")[0], "human")
    before = {
        row["user"]["battleTag"]: row["seed"] for row in entrants(client, night["id"])
    }

    enrol("Late#1004", 1420)
    assert sign_up(client, "Late#1004", "late", "human").status_code == 200

    after = {
        row["user"]["battleTag"]: row["seed"] for row in entrants(client, night["id"])
    }
    assert after == {**before, "Late#1004": 3}


def test_an_admin_places_an_unplaced_row_and_a_recut_leaves_it(
    client: Client,
    auth_headers: dict[str, str],
    seeded: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The hand placement is the only override, and it stands through a re-cut."""
    silent_w3c(monkeypatch)
    night = open_night(client, auth_headers)
    enrol("Rated#1001", 1500)
    sign_up(client, "Rated#1001", "rated", "human")
    sign_up(client, "Ghost#9999", "ghost", "human")
    waiting = next(
        row for row in entrants(client, night["id"]) if row["division_id"] is None
    )
    bracket = next(
        row["division_id"]
        for row in entrants(client, night["id"])
        if row["division_id"] is not None
    )

    placed = client.put(
        f"/events/{night['id']}/entrants/{waiting['id']}",
        json={"division_id": bracket},
        headers=auth_headers,
    )

    assert placed.status_code == 200, placed.text
    assert (placed.json()["division_id"], placed.json()["seed"]) == (bracket, 2)
    assert placed.json()["manual_placement"] is True
    enrol("Later#1002", 1550)
    sign_up(client, "Later#1002", "later", "human")
    rows = {row["user"]["battleTag"]: row for row in entrants(client, night["id"])}
    assert rows["Ghost#9999"]["division_id"] == bracket
    assert rows["Ghost#9999"]["seed"] == 2


def test_closing_a_night_deletes_the_series_nobody_played(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """One scored series stands; the pending end of every chain goes.

    Every series left then carries a result, so the night reads finished.
    """
    night = open_night(client, auth_headers)
    # Two brackets, one chain each: the top chain is played, the low one is not
    for tag, mmr in (
        ("C1#1001", 1400),
        ("T1#1004", 1700),
        ("C2#1002", 1300),
        ("T2#1005", 1650),
    ):
        enrol(tag, mmr)
        sign_up(client, tag, tag.split("#")[0], "human")

    stage = night["stages"][0]["id"]
    top, low = brackets_of(client, night["id"])
    played = open_chain(night["id"], stage, top)
    open_chain(night["id"], stage, low)
    rows = stage_series(client, night["id"], stage)["series"]
    assert len(rows) == 2
    assert score(client, auth_headers, played, 1, 0).status_code == 200

    closed = client.post(f"/koth/nights/{night['id']}/close", headers=auth_headers)

    assert closed.status_code == 200, closed.text
    assert closed.json()["signups_open"] is False
    assert closed.json()["phase"] == "finished"
    left = stage_series(client, night["id"], stage)["series"]
    assert [row["id"] for row in left] == [played]


def test_a_signup_that_names_no_race_takes_his_race_inside_the_window(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A stale rating never pins the race: the pick reads the same window as the check."""
    night = open_night(client, auth_headers)
    user_id = enrol("Switch#1001", 1500, race=Race.NE)
    with Session.begin() as session:
        session.add(
            W3CStats(user_id=user_id, race=Race.HU, wc3_season=15, games=50, mmr=1900)
        )

    resp = sign_up(client, "Switch#1001", "switch")

    assert resp.status_code == 200, resp.text
    assert resp.json()["message"] == "switch signed up for Bracket 2 (1500 MMR)"
    rows = entrants(client, night["id"])
    assert [(row["race"], row["mmr"]) for row in rows] == [("NE", 1500)]


def test_a_chain_with_every_series_scored_still_reads_running(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A night ends when the admin closes it, not when the last result lands."""
    night = open_night(client, auth_headers)
    for tag, mmr in (("A#1001", 1400), ("B#1002", 1300)):
        enrol(tag, mmr)
        sign_up(client, tag, tag.split("#")[0], "human")
    row = open_chain(night["id"], night["stages"][0]["id"])
    assert score(client, auth_headers, row, 1, 0).status_code == 200

    resp = client.get(f"/events/{night['id']}")

    assert resp.status_code == 200, resp.text
    assert resp.json()["phase"] == "running"
    assert resp.json()["closed_at"] is None


def test_a_closed_night_reads_finished_and_grows_no_chain(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The close stamps the night; the stamp is what the phase reads."""
    night = open_night(client, auth_headers)
    stage = night["stages"][0]["id"]
    for tag, mmr in (("A#1001", 1400), ("B#1002", 1300), ("C#1003", 1350)):
        enrol(tag, mmr)
        sign_up(client, tag, tag.split("#")[0], "human")
    late = [row["id"] for row in entrants(client, night["id"])][-1]

    closed = client.post(f"/koth/nights/{night['id']}/close", headers=auth_headers)

    assert closed.status_code == 200, closed.text
    assert closed.json()["closed_at"] is not None
    assert closed.json()["phase"] == "finished"
    resp = client.post(
        f"/events/{night['id']}/stages/{stage}/series",
        json={"entrant_id": late},
        headers=auth_headers,
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"] == "The night is closed"


def test_the_chain_refuses_a_player_it_already_names(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """One seat per player in a chain, whichever row asks for the second."""
    night = open_night(client, auth_headers)
    stage = night["stages"][0]["id"]
    for tag, mmr in (("A#1001", 1400), ("B#1002", 1300)):
        enrol(tag, mmr)
        sign_up(client, tag, tag.split("#")[0], "human")
    open_chain(night["id"], stage)
    playing = entrants(client, night["id"])[0]["id"]

    resp = client.post(
        f"/events/{night['id']}/stages/{stage}/series",
        json={"entrant_id": playing},
        headers=auth_headers,
    )

    assert resp.status_code == 400, resp.text
    assert resp.json()["error"] == "This player already plays in that chain"
