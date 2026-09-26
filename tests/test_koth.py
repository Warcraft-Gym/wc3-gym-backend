"""The old /koth/* paths, answered from the event model.

Nightbot, the overlay and the bookmarks of the run crew still call these
paths, so every test here drives the old route and reads the old payload,
while the rows behind it are the event, its entrants and the series of its
chains. The rating a signup cuts on is the W3C stats the app stored, so
nothing here reaches w3champions.
"""

from typing import Any

import pytest
from fastapi import FastAPI
from httpx2 import Client

from app.core.db import Session
from app.models.base import ident
from app.models.enums import Race
from app.models.user import User
from app.models.w3c_stats import W3CStats
from app.services.w3c import W3CService
from tests.seed import active

EVENT = {"name": "KOTH 1", "event_date": "2026-01-10T20:00:00Z"}
SIGNUP = {
    "client_token": "test-nightbot-token",
    "twitch_username": "streamer",
    "battle_tag": "S#1234",
}


def rate(tag: str, race: Race, mmr: int, season: int = 20) -> int:
    """Give the player behind a battle tag one W3C rating the signup reads."""
    from app.services.battle_tags import attach_tag, person_by_tag

    with Session.begin() as session:
        user = person_by_tag(session, tag)
        if user is None:
            user = User(
                name=tag.split("#")[0],
                battle_tags=active(tag),
                discordTag="",
                discordId="",
                race=race,
            )
            session.add(user)
            attach_tag(session, user, tag, "signup")
        session.add(
            W3CStats(
                user_id=ident(user), race=race, wc3_season=season, games=50, mmr=mmr
            )
        )
        return ident(user)


def silent_w3c(monkeypatch: pytest.MonkeyPatch) -> None:
    """W3Champions knows nobody, so a signup that asks it reaches no network."""
    monkeypatch.setattr(W3CService, "current_season", lambda self: 20)
    monkeypatch.setattr(
        W3CService,
        "get_player_stats",
        lambda self, bnet_name, season_override=None: [],
    )


def unplaced(client: Client, event_id: int) -> list[str]:
    """The battle tags of the rows no bracket holds."""
    rows = client.get(f"/events/{event_id}/entrants").json()
    return [row["user"]["battleTag"] for row in rows if row["division_id"] is None]


def sign_up(client: Client, tag: str, race: str | None = None, **body: Any) -> Any:  # noqa: ANN401
    """The Nightbot JSON signup, the route the chat bot and the bot post to."""
    return client.post(
        "/koth/signups",
        json={**SIGNUP, "battle_tag": tag, **({"race": race} if race else {}), **body},
    )


@pytest.fixture
def koth(client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]) -> Any:  # noqa: ANN401
    """A night open for signups with two rated players in bracket 1."""
    rate("P1#1111", Race.HU, 1400)
    rate("P2#2222", Race.OC, 1420)
    event = client.post("/koth/events", headers=auth_headers, json=EVENT)
    assert event.status_code == 201, event.text
    ids = []
    for tag, race in (("P1#1111", "human"), ("P2#2222", "orc")):
        resp = sign_up(client, tag, race)
        assert resp.status_code == 201, resp.text
        ids.append(resp.json()["id"])
    return {"event_id": event.json()["id"], "signup_ids": ids}


def pair(
    client: Client, koth: dict[str, Any], headers: dict[str, str]
) -> dict[str, Any]:
    """The series an admin makes of the two entrants of bracket 1, by hand."""
    one, two = koth["signup_ids"]
    resp = client.post(
        "/koth/matches",
        headers=headers,
        json={
            "event_id": koth["event_id"],
            "game_mode": "1v1",
            "num_teams": 2,
            "participants": [
                {"signup_id": one, "team_number": 1},
                {"signup_id": two, "team_number": 2},
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def throne(
    client: Client, koth: dict[str, Any], headers: dict[str, str]
) -> dict[str, Any]:
    """The one series of bracket 1; the admin pairs it when none stands yet."""
    matches = client.get(f"/koth/events/{koth['event_id']}/matches").json()
    if not matches:
        matches = [pair(client, koth, headers)]
    assert len(matches) == 1, matches
    return matches[0]


def test_a_night_draws_nothing_and_the_admin_pairs_by_hand(
    client: Client, auth_headers: dict[str, str], koth: dict[str, Any]
) -> None:
    """Two signups open no series; the pair an admin makes reads in the old shape."""
    assert client.get(f"/koth/events/{koth['event_id']}/matches").json() == []

    match = pair(client, koth, auth_headers)

    assert (match["bracket"], match["game_mode"], match["num_teams"]) == (1, "1v1", 2)
    assert match["winner_team_number"] is None
    assert {p["signup"]["battle_tag"] for p in match["participants"]} == {
        "P1#1111",
        "P2#2222",
    }


def test_a_match_takes_its_bracket_from_the_participants(
    client: Client, auth_headers: dict[str, str], koth: dict[str, Any]
) -> None:
    one, two = koth["signup_ids"]
    resp = client.post(
        "/koth/matches",
        headers=auth_headers,
        json={
            "event_id": koth["event_id"],
            "game_mode": "1v1",
            "num_teams": 2,
            "participants": [
                {"signup_id": one, "team_number": 1},
                {"signup_id": two, "team_number": 2},
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    match = resp.json()
    assert match["bracket"] == 1
    assert len(match["participants"]) == 2
    assert {p["signup"]["battle_tag"] for p in match["participants"]} == {
        "P1#1111",
        "P2#2222",
    }


def test_a_result_crowns_the_winner_and_retires_the_loser(
    client: Client, auth_headers: dict[str, str], koth: dict[str, Any]
) -> None:
    """Scoring the series is the whole crown: the winner holds the throne."""
    one, two = koth["signup_ids"]
    match = throne(client, koth, auth_headers)
    winner = next(
        p["team_number"] for p in match["participants"] if p["signup_id"] == one
    )

    resp = client.put(
        f"/koth/matches/{match['id']}/result",
        headers=auth_headers,
        json={"winner_team_number": winner},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["winner_team_number"] == winner

    signups = {
        s["id"]: s
        for s in client.get(f"/koth/events/{koth['event_id']}").json()["signups"]
    }
    assert (signups[one]["is_king"], signups[one]["is_active"]) == (1, 1)
    assert (signups[two]["is_king"], signups[two]["is_active"]) == (0, 0)


def test_set_king_reorders_an_unplayed_chain_and_then_refuses(
    client: Client, auth_headers: dict[str, str], koth: dict[str, Any]
) -> None:
    """An admin names the defender before the first result, never after one."""
    one, two = koth["signup_ids"]
    match = throne(client, koth, auth_headers)
    seats = {p["signup_id"]: p["team_number"] for p in match["participants"]}
    waiting = one if seats[one] == 2 else two

    resp = client.post(f"/koth/signups/{waiting}/king", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    moved = throne(client, koth, auth_headers)
    assert {p["signup_id"]: p["team_number"] for p in moved["participants"]}[
        waiting
    ] == 1

    client.put(
        f"/koth/matches/{moved['id']}/result",
        headers=auth_headers,
        json={"winner_team_number": 1},
    )
    refused = client.post(f"/koth/signups/{waiting}/king", headers=auth_headers)
    assert refused.status_code == 400
    assert "decides the king by results" in refused.json()["error"]


def test_the_crown_is_never_added_or_taken_by_hand(
    client: Client, auth_headers: dict[str, str], koth: dict[str, Any]
) -> None:
    """A bracket holds one king and the night wins him, so both paths answer 400."""
    one = koth["signup_ids"][0]
    for method, path in (("POST", "add-king"), ("DELETE", "king")):
        resp = client.request(
            method, f"/koth/signups/{one}/{path}", headers=auth_headers
        )
        assert resp.status_code == 400, resp.text
        assert "decides the king by results" in resp.json()["error"]


def test_the_kings_read_names_the_winner_of_each_chain(
    client: Client, auth_headers: dict[str, str], koth: dict[str, Any]
) -> None:
    """No result, no king; one result, one king in that bracket."""
    assert client.get(f"/koth/events/{koth['event_id']}/kings").json() == {}

    match = throne(client, koth, auth_headers)
    client.put(
        f"/koth/matches/{match['id']}/result",
        headers=auth_headers,
        json={"winner_team_number": 2},
    )

    kings = client.get(f"/koth/events/{koth['event_id']}/kings").json()
    seated = next(
        p["signup_id"] for p in match["participants"] if p["team_number"] == 2
    )
    assert [s["id"] for s in kings["1"]] == [seated]


def test_a_bracket_change_touches_only_the_bracket(
    client: Client, auth_headers: dict[str, str], koth: dict[str, Any]
) -> None:
    one = koth["signup_ids"][0]
    before = client.get(f"/koth/events/{koth['event_id']}").json()["signups"]
    before = next(s for s in before if s["id"] == one)

    resp = client.put(
        f"/koth/signups/{one}/bracket", headers=auth_headers, json={"bracket": 3}
    )
    assert resp.status_code == 200, resp.text
    after = resp.json()
    assert after["bracket"] == 3
    for field in ("battle_tag", "w3c_name", "race", "mmr", "is_king", "is_active"):
        assert after[field] == before[field]


def test_an_event_update_keeps_the_fields_it_was_not_given(
    client: Client, auth_headers: dict[str, str], koth: dict[str, Any]
) -> None:
    before = client.get(f"/koth/events/{koth['event_id']}").json()
    resp = client.put(
        f"/koth/events/{koth['event_id']}",
        headers=auth_headers,
        json={"description": "now with a description"},
    )
    assert resp.status_code == 200, resp.text
    after = resp.json()
    assert after["description"] == "now with a description"
    assert after["name"] == before["name"]
    assert after["event_date"] == before["event_date"]
    assert after["bracket_1_threshold"] == before["bracket_1_threshold"]


def test_a_threshold_move_recuts_the_next_signup(
    client: Client, auth_headers: dict[str, str], koth: dict[str, Any]
) -> None:
    """The thresholds ride the brackets, so a move lands the next player higher."""
    resp = client.put(
        f"/koth/events/{koth['event_id']}",
        headers=auth_headers,
        json={"bracket_1_threshold": 1300},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["bracket_1_threshold"] == 1300

    rate("P3#3333", Race.NE, 1350)
    assert sign_up(client, "P3#3333", "nightelf").json()["bracket"] == 2


def test_one_event_is_active_after_an_activation(
    client: Client, auth_headers: dict[str, str], koth: dict[str, Any]
) -> None:
    client.post(f"/koth/nights/{koth['event_id']}/close", headers=auth_headers)
    second = client.post(
        "/koth/events",
        headers=auth_headers,
        json={"name": "KOTH 2", "event_date": "2026-01-17T20:00:00Z"},
    ).json()

    def active_ids() -> list[int]:
        return [e["id"] for e in client.get("/koth/events").json() if e["is_active"]]

    for event_id in (koth["event_id"], second["id"]):
        resp = client.post(f"/koth/events/{event_id}/activate", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["is_active"] is True
        assert active_ids() == [event_id]

    assert (
        client.post("/koth/events/9999/activate", headers=auth_headers).status_code
        == 404
    )
    assert active_ids() == [second["id"]]


def test_a_deleted_event_takes_its_chain_with_it(
    client: Client, auth_headers: dict[str, str], koth: dict[str, Any]
) -> None:
    """The night, its brackets, its entrants and its series all go."""
    resp = client.delete(f"/koth/events/{koth['event_id']}", headers=auth_headers)
    assert resp.status_code == 204, resp.text
    assert client.get(f"/koth/events/{koth['event_id']}").status_code == 404
    assert client.get("/koth/events").json() == []


def test_bad_koth_input_answers_400(
    client: Client, auth_headers: dict[str, str], koth: dict[str, Any]
) -> None:
    """The rule checks in the module answer 400, not 500."""
    one, two = koth["signup_ids"]

    resp = client.put(
        f"/koth/signups/{one}/bracket", headers=auth_headers, json={"bracket": 9}
    )
    assert resp.status_code == 400
    assert "Bracket" in resp.json()["error"]

    resp = client.post(
        "/koth/matches",
        headers=auth_headers,
        json={
            "event_id": koth["event_id"],
            "game_mode": "1v1",
            "num_teams": 2,
            "participants": [
                {"signup_id": one, "team_number": 1},
                {"signup_id": two, "team_number": 1},
            ],
        },
    )
    assert resp.status_code == 400
    assert "teams" in resp.json()["error"]

    resp = client.put(
        f"/koth/matches/{throne(client, koth, auth_headers)['id']}/result",
        headers=auth_headers,
        json={"winner_team_number": 5},
    )
    assert resp.status_code == 400
    assert "Winner team number" in resp.json()["error"]


def test_a_failed_match_creation_writes_nothing(
    client: Client, auth_headers: dict[str, str], koth: dict[str, Any]
) -> None:
    """One transaction: an unknown participant leaves no half-made match."""
    one, _ = koth["signup_ids"]
    resp = client.post(
        "/koth/matches",
        headers=auth_headers,
        json={
            "event_id": koth["event_id"],
            "game_mode": "1v1",
            "num_teams": 2,
            "participants": [
                {"signup_id": one, "team_number": 1},
                {"signup_id": 99999, "team_number": 2},
            ],
        },
    )
    assert resp.status_code == 404
    assert client.get(f"/koth/events/{koth['event_id']}/matches").json() == []


def test_a_deleted_match_leaves_the_chain(
    client: Client, auth_headers: dict[str, str], koth: dict[str, Any]
) -> None:
    match = throne(client, koth, auth_headers)
    assert (
        client.delete(f"/koth/matches/{match['id']}", headers=auth_headers).status_code
        == 204
    )
    assert client.get(f"/koth/events/{koth['event_id']}/matches").json() == []


# ---------- The signup flow, cut on the ratings the app stored ----------


def test_the_signup_post_ignores_the_token(
    client: Client, koth: dict[str, Any]
) -> None:
    """The POST is open by decision; a wrong token no longer blocks a signup."""
    rate("S#5678", Race.HU, 1400)
    resp = sign_up(client, "S#5678", "human", client_token="wrong")
    assert resp.status_code == 201, resp.text


def test_a_wrong_nightbot_query_token_answers_401(
    client: Client, seeded: dict[str, Any]
) -> None:
    resp = client.get(
        "/koth/signup", params={"token": "wrong", "twitch": "s", "battletag": "S#1"}
    )
    assert resp.status_code == 401


def test_a_deployment_without_a_nightbot_token_answers_401(
    client: Client, seeded: dict[str, Any]
) -> None:
    """A missing setting is an auth failure, not a 404 naming the setting."""
    from app.models.settings import Settings

    with Session.begin() as session:
        session.query(Settings).filter_by(key="KOTH_NIGHTBOT_TOKEN").delete()

    resp = client.get(
        "/koth/signup", params={"token": "x", "twitch": "s", "battletag": "S#1"}
    )
    assert resp.status_code == 401, resp.text


def test_a_signup_missing_a_field_is_refused(
    client: Client, seeded: dict[str, Any]
) -> None:
    # The body model refuses before the handler runs, so the POST answers 422
    resp = client.post(
        "/koth/signups",
        json={"client_token": "test-nightbot-token", "twitch_username": "streamer"},
    )
    assert resp.status_code == 422
    assert "battle_tag" in resp.json()["error"]
    # The GET keeps its optional query params and the handler's 400
    resp = client.get(
        "/koth/signup", params={"token": "test-nightbot-token", "twitch": "streamer"}
    )
    assert resp.status_code == 400


def test_an_unknown_race_answers_400(client: Client, koth: dict[str, Any]) -> None:
    resp = sign_up(client, "S#1234", "gnome")
    assert resp.status_code == 400
    assert "Valid options" in resp.json()["error"]


def test_a_signup_picks_the_highest_mmr_race(
    client: Client, koth: dict[str, Any]
) -> None:
    rate("S#1234", Race.HU, 1500)
    rate("S#1234", Race.OC, 1555)
    resp = sign_up(client, "S#1234")
    assert resp.status_code == 201, resp.text
    signup = resp.json()
    assert (signup["race"], signup["mmr"], signup["bracket"]) == ("OC", 1555, 2)


def test_a_requested_race_takes_that_races_mmr(
    client: Client, koth: dict[str, Any]
) -> None:
    rate("S#1234", Race.HU, 1500)
    rate("S#1234", Race.OC, 1555)
    resp = sign_up(client, "S#1234", "human")
    assert resp.status_code == 201, resp.text
    signup = resp.json()
    assert (signup["race"], signup["mmr"]) == ("HU", 1500)


def test_the_brackets_cut_at_the_event_thresholds(
    client: Client, koth: dict[str, Any]
) -> None:
    """KOTH 1 cuts at 1450 and 1600: below, between, at-or-above."""
    for name, mmr, bracket in (("low", 1449, 1), ("mid", 1599, 2), ("top", 1600, 3)):
        rate(f"{name}#1001", Race.UD, mmr)
        resp = sign_up(client, f"{name}#1001", "undead")
        assert resp.status_code == 201, resp.text
        assert resp.json()["bracket"] == bracket


def test_a_quiet_player_falls_back_one_season(
    client: Client, koth: dict[str, Any]
) -> None:
    """The rating window is the current W3C season and the one before it."""
    rate("S#1234", Race.NE, 1700, season=19)
    resp = sign_up(client, "S#1234")
    assert resp.status_code == 201, resp.text
    assert (resp.json()["race"], resp.json()["mmr"]) == ("NE", 1700)


def test_no_stats_in_the_window_signs_up_unplaced(
    client: Client, koth: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rating nobody can read is no refusal: the row stands for the admin."""
    silent_w3c(monkeypatch)
    rate("S#1234", Race.HU, 1500, season=18)  # one season too old
    resp = sign_up(client, "S#1234")

    assert resp.status_code == 201, resp.text
    event = client.get("/koth/events/active").json()
    assert "S#1234" in [s["battle_tag"] for s in event["signups"]]
    assert unplaced(client, koth["event_id"]) == ["S#1234"]


def test_a_bad_battle_tag_is_refused(client: Client, koth: dict[str, Any]) -> None:
    """The tag is the identity, so a typo writes no second player."""
    resp = sign_up(client, "Typo", "human")

    assert resp.status_code == 400, resp.text
    assert "Name#1234" in resp.json()["error"]


def test_a_second_race_enters_beside_the_first_signup(
    app: FastAPI, client: Client, koth: dict[str, Any]
) -> None:
    """One entrant per race: each race sits in the bracket its own rating cuts."""
    rate("P3#3333", Race.HU, 1400)
    rate("P3#3333", Race.NE, 1700)

    first = sign_up(client, "P3#3333", "human")
    second = sign_up(client, "P3#3333", "nightelf")

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    signups = client.get(f"/koth/events/{koth['event_id']}/signups").json()
    mine = sorted(
        (s["race"], s["bracket"]) for s in signups if s["battle_tag"] == "P3#3333"
    )
    assert mine == [("HU", 1), ("NE", 3)]


def test_the_profile_signup_reads_the_battle_tag_of_the_logged_in_player(
    client: Client, koth: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A logged-in player names a race only; the battle tag comes from his row."""
    from sqlalchemy import update
    from sqlmodel import col

    from tests.test_discord_auth import ACCOUNT, SESSION, stub_clerk

    rate("P4#4444", Race.NE, 1700)
    stub_clerk(monkeypatch)
    with Session.begin() as session:
        session.execute(
            update(User)
            .where(col(User.battleTag) == "P4#4444")
            .values(discordId=ACCOUNT["id"])
        )

    resp = client.post(
        "/koth/signups/me", json={"races": ["nightelf"]}, headers=SESSION
    )
    assert resp.status_code == 201, resp.text
    assert [(s["battle_tag"], s["race"], s["bracket"]) for s in resp.json()] == [
        ("P4#4444", "NE", 3)
    ]


def test_a_player_withdraws_their_own_signup(
    client: Client, koth: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Withdraw once; a second call has nothing left to withdraw."""
    from sqlalchemy import update
    from sqlmodel import col

    from tests.test_discord_auth import ACCOUNT, SESSION, stub_clerk

    rate("P4#4444", Race.NE, 1700)
    stub_clerk(monkeypatch)
    with Session.begin() as session:
        session.execute(
            update(User)
            .where(col(User.battleTag) == "P4#4444")
            .values(discordId=ACCOUNT["id"])
        )
    assert (
        client.post(
            "/koth/signups/me", json={"races": ["nightelf"]}, headers=SESSION
        ).status_code
        == 201
    )

    assert client.delete("/koth/signups/me", headers=SESSION).status_code == 204
    signups = client.get(f"/koth/events/{koth['event_id']}/signups").json()
    mine = [s for s in signups if s["battle_tag"] == "P4#4444"]
    assert [s["is_active"] for s in mine] == [0]

    assert client.delete("/koth/signups/me", headers=SESSION).status_code == 404


def test_a_signup_carries_the_flag_of_its_player_row(
    client: Client, koth: dict[str, Any]
) -> None:
    """P1#1111 is a seeded user from Germany, P2#2222 one from the US."""
    event = client.get(f"/koth/events/{koth['event_id']}").json()
    by_tag = {s["battle_tag"]: s for s in event["signups"]}
    assert by_tag["P1#1111"]["country"] == "DE"
    signups = client.get(f"/koth/events/{koth['event_id']}/signups").json()
    assert {s["battle_tag"]: s["country"] for s in signups} == {
        "P1#1111": "DE",
        "P2#2222": "US",
    }


def test_the_admin_signup_lands_on_the_event_he_names(
    client: Client, koth: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    """The admin adds a player to the event on screen, not to the open one."""
    client.post(f"/koth/nights/{koth['event_id']}/close", headers=auth_headers)
    later = client.post(
        "/koth/events",
        headers=auth_headers,
        json={"name": "KOTH 2", "event_date": "2026-02-10T20:00:00Z"},
    ).json()
    rate("P3#3333", Race.HU, 1400)

    resp = client.post(
        "/koth/signups/admin",
        headers=auth_headers,
        json={
            "twitch_username": "player_three",
            "battle_tag": "P3#3333",
            "races": ["human"],
            "event_id": koth["event_id"],
        },
    )

    assert resp.status_code == 201, resp.text
    assert [s["event_id"] for s in resp.json()] == [koth["event_id"]]
    open_night = client.get(f"/koth/events/{later['id']}/signups").json()
    assert "P3#3333" not in [s["battle_tag"] for s in open_night]
