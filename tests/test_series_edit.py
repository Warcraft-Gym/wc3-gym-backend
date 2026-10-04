"""A captain adds, edits and deletes the published series of his team's
fixture, and whoever may report a result takes it back.

The seeded fixture is Alpha against Beta. The played series is P1 (Alpha)
against P3 (Beta), 2-1; the open series is P2 (Alpha) against P4 (Beta).
"""

from collections.abc import Callable
from typing import Any

import pytest
from httpx2 import Client
from sqlalchemy import select
from sqlmodel import col

from app.core.db import Session
from app.models.discord_post import DiscordPost
from app.models.relationships import DBTeamSeasonCaptain
from app.models.series import Series
from app.models.settings import Settings
from app.models.team import Team
from app.models.team_season import DBTeamSeason
from app.services import discord, series_games

RESULTS = f"{discord.API_URL}/channels/results/messages"


def seat(seeded: dict[str, Any], team: str, player: int) -> None:
    """Seat a captain straight in the table, so no Discord role is granted."""
    with Session.begin() as session:
        session.add(
            DBTeamSeasonCaptain(
                team_id=seeded[f"team_{team}_id"],
                season_id=seeded["season_id"],
                user_id=seeded["player_ids"][player],
            )
        )


def seat_on_gamma(seeded: dict[str, Any], player: int) -> None:
    """Seat a captain of Gamma, a team of the season that plays no seeded match."""
    with Session.begin() as session:
        gamma = Team(name="Gamma", league_id=seeded["league_id"])
        session.add(gamma)
        session.flush()
        assert gamma.id is not None
        session.add(DBTeamSeason(team_id=gamma.id, season_id=seeded["season_id"]))
        session.add(
            DBTeamSeasonCaptain(
                team_id=gamma.id,
                season_id=seeded["season_id"],
                user_id=seeded["player_ids"][player],
            )
        )


def new_series(seeded: dict[str, Any], host: int = 1) -> dict[str, Any]:
    """P2 (Alpha) against P3 (Beta), a pairing the fixture does not hold yet."""
    players = seeded["player_ids"]
    return {
        "match_id": seeded["match_id"],
        "player1_id": players[1],
        "player2_id": players[2],
        "host_player_id": players[host],
    }


def kind_of(series_id: int) -> str:
    """The result kind, which the series answer does not carry."""
    with Session() as session:
        return session.get_one(Series, series_id).result_kind


@pytest.mark.parametrize(("team", "captain"), [("a", 1), ("b", 3)])
def test_a_captain_of_either_team_edits_a_series_he_does_not_play(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    team: str,
    captain: int,
) -> None:
    seat(seeded, team, captain)
    p3 = seeded["player_ids"][2]
    resp = client.put(
        f"/series/{seeded['series_played_id']}",
        json={
            "date_time": "2026-01-09T20:00:00Z",
            "player1_score": 1,
            "player2_score": 2,
            "player2_off_race": "UD",
            "host_player_id": p3,
            "is_fantasy_match": True,
        },
        headers=member(str(captain + 1)),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["date_time"].startswith("2026-01-09T20:00:00")
    assert (body["player1_score"], body["player2_score"]) == (1, 2)
    assert body["player2_off_race"] == "UD"
    assert body["host_player_id"] == p3
    assert body["is_fantasy_match"] is True


@pytest.mark.parametrize("change", ["player1_id", "match_id", "force"])
def test_who_plays_the_fixture_and_force_stay_an_admins(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    change: str,
) -> None:
    seat(seeded, "a", 1)
    url = f"/series/{seeded['series_played_id']}"
    sent: dict[str, Any] = {
        "player1_id": {"player1_id": seeded["player_ids"][1]},
        "match_id": {"match_id": seeded["match_id"]},
        "force": {"date_time": "2026-01-09T20:00:00Z"},
    }[change]
    if change == "force":
        url += "?force=true"
    resp = client.put(url, json=sent, headers=member("2"))
    assert resp.status_code == 403, resp.text


def test_a_player_who_captains_no_team_edits_through_the_report_alone(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    resp = client.put(
        f"/series/{seeded['series_played_id']}",
        json={"is_fantasy_match": True},
        headers=member("1"),
    )
    assert resp.status_code == 403, resp.text


def test_the_host_is_one_of_the_two_players(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    seat(seeded, "a", 1)
    resp = client.put(
        f"/series/{seeded['series_played_id']}",
        json={"host_player_id": seeded["player_ids"][3]},
        headers=member("2"),
    )
    assert resp.status_code == 400, resp.text


def test_a_player_takes_back_his_result_with_its_games_and_races(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    series_id = seeded["series_played_id"]
    series_games.record(
        series_id,
        [
            {"game_no": 1, "winner_side": "A"},
            {"game_no": 2, "winner_side": "B"},
            {"game_no": 3, "winner_side": "A"},
        ],
    )
    headers = member("1")
    resp = client.put(
        f"/player-series/{series_id}",
        json={"player1_off_race": "OC"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    resp = client.delete(f"/series/{series_id}/result", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["player1_score"], body["player2_score"]) == (None, None)
    assert body["player1_off_race"] is None
    assert kind_of(series_id) == "played"
    assert series_games.for_series(series_id) == []


def test_a_captain_takes_back_a_result_of_his_fixture(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    seat(seeded, "b", 3)
    resp = client.delete(
        f"/series/{seeded['series_played_id']}/result", headers=member("4")
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["player1_score"] is None


def test_a_member_outside_the_series_clears_nothing(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    resp = client.delete(
        f"/series/{seeded['series_played_id']}/result", headers=member("4")
    )
    assert resp.status_code == 403, resp.text


def test_an_admin_alone_clears_a_walkover(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    member: Callable[..., dict[str, str]],
) -> None:
    series_id = seeded["series_open_id"]
    resp = client.put(
        f"/series/{series_id}/result-kind",
        json={"result_kind": "walkover", "winner": 1},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text

    resp = client.delete(f"/series/{series_id}/result", headers=member("2"))
    assert resp.status_code == 403, resp.text

    resp = client.delete(f"/series/{series_id}/result", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["player1_score"] is None
    assert kind_of(series_id) == "played"


def test_a_cleared_result_takes_its_card_down_and_the_next_report_posts_anew(
    client: Client,
    discord_calls: list,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    replay_uploaded: Callable[..., None],
) -> None:
    with Session.begin() as session:
        session.add(Settings(key="results_channel_id", value="results"))
    series_id = seeded["series_open_id"]
    headers = member("2")
    replay_uploaded(series_id, 1, 2)

    def report() -> None:
        resp = client.put(
            f"/player-series/{series_id}",
            headers=headers,
            json={"action": "score_updated", "player1_score": 2, "player2_score": 0},
        )
        assert resp.status_code == 200, resp.text

    report()
    resp = client.delete(f"/series/{series_id}/result", headers=headers)
    assert resp.status_code == 200, resp.text
    report()

    assert [call[:2] for call in discord_calls] == [
        ("POST", RESULTS),
        ("DELETE", f"{RESULTS}/msg-1"),
        ("POST", RESULTS),
    ]
    with Session() as session:
        posts = session.scalars(
            select(DiscordPost).where(col(DiscordPost.subject_id) == series_id)
        ).all()
    assert [post.message_id for post in posts] == ["msg-2"]


def test_a_captain_adds_a_series_while_the_round_has_room(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    member: Callable[..., dict[str, str]],
) -> None:
    seat(seeded, "a", 1)
    headers = member("2")
    # The seeded fixture already holds the two series of its round
    resp = client.post("/series", json=new_series(seeded), headers=headers)
    assert resp.status_code == 409, resp.text

    resp = client.put(
        f"/events/{seeded['season_id']}",
        json={"series_per_round": 3},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    resp = client.post("/series", json=new_series(seeded), headers=headers)
    assert resp.status_code == 201, resp.text
    assert resp.json()["player1_id"] == seeded["player_ids"][1]


def test_a_captain_names_one_of_the_two_players_as_the_host(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    member: Callable[..., dict[str, str]],
) -> None:
    seat(seeded, "b", 3)
    resp = client.put(
        f"/events/{seeded['season_id']}",
        json={"series_per_round": 3},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    resp = client.post("/series", json=new_series(seeded, host=0), headers=member("4"))
    assert resp.status_code == 400, resp.text


def test_a_captain_of_another_team_adds_and_deletes_nothing(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    seat_on_gamma(seeded, 1)
    headers = member("2")
    resp = client.post("/series", json=new_series(seeded), headers=headers)
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"] == "Your team does not play this match"
    resp = client.delete(f"/series/{seeded['series_open_id']}", headers=headers)
    assert resp.status_code == 403, resp.text
    resp = client.put(
        f"/series/{seeded['series_open_id']}",
        json={"is_fantasy_match": True},
        headers=headers,
    )
    assert resp.status_code == 403, resp.text


def test_a_captain_deletes_a_series_of_his_fixture(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    seat(seeded, "b", 3)
    series_id = seeded["series_open_id"]
    resp = client.delete(f"/series/{series_id}", headers=member("4"))
    assert resp.status_code == 204, resp.text
    assert client.get(f"/series/{series_id}").status_code == 404


def test_a_player_who_captains_no_team_deletes_nothing(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    resp = client.delete(f"/series/{seeded['series_played_id']}", headers=member("1"))
    assert resp.status_code == 403, resp.text
