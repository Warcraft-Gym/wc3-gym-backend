"""One aggregated read fills the draft board of a match, and one on-demand
read answers the meetings of a pair.

The board is a captain's read of his own match, and every figure on it is
derived: no route here stores anything. The statement counts are pinned,
because the whole point of the board is that it costs the same whatever the
size of the two rosters.
"""

import json
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import pytest
from httpx2 import Client
from sqlalchemy import select
from sqlmodel import col

from app.core.db import Session
from app.models.base import ident
from app.models.enums import Race, StageFormat
from app.models.event_stage import MAX_MMR_DIFFERENCE, EventStage
from app.models.relationships import DBEventRound, DBUserSeasonSignup
from app.models.season import Season
from app.models.series import Series
from app.models.team import Team
from app.models.user import User
from app.models.user_block import UserBlock
from app.models.user_team_season import DBUserTeamSeason
from app.models.w3c_ladder_match import W3CLadderMatch
from app.models.w3c_stats import W3CStats
from tests.test_discord_auth import SESSION, stub_clerk
from tests.test_query_budget import count_statements

RACES = [Race.HU, Race.OC, Race.NE, Race.UD]


@pytest.fixture
def board_league(seeded: dict[str, Any]) -> dict[str, Any]:
    """The seeded league with what the board reads: a captain-draft stage, a
    signup race per player, W3C stats, ladder rows and one blocked evening.

    P1 and P3 hold the ladder history; P2 and P4 hold none, so the games rule
    and the empty form both show.
    """
    players = seeded["player_ids"]
    with Session() as session:
        session.add(
            EventStage(
                event_id=seeded["season_id"],
                position=1,
                format=StageFormat.gnl,
                max_mmr_difference=120,
            )
        )
        for user_id in players:
            session.add(
                DBUserSeasonSignup(
                    user_id=user_id, season_id=seeded["season_id"], race=Race.HU
                )
            )
        # P1 is rated and has played enough; P3 is rated with three games only
        session.add_all(
            [
                W3CStats(
                    user_id=players[0], wc3_season=9, race=Race.HU, games=40, mmr=1500
                ),
                W3CStats(
                    user_id=players[2], wc3_season=9, race=Race.HU, games=3, mmr=1400
                ),
            ]
        )
        start = datetime(2026, 1, 6, 12, 0, tzinfo=UTC)
        for index in range(12):
            session.add(
                W3CLadderMatch(
                    user_id=players[0],
                    w3c_match_id=f"m{index}",
                    wc3_season=9,
                    start_time=start + timedelta(hours=index),
                    duration_s=600,
                    race=Race.HU,
                    opp_race=RACES[index % 4],
                    won=index % 2 == 0,
                    mmr_before=1490 + index,
                    mmr_after=1500 + index,
                )
            )
        # P1 blocks Monday morning, the one Monday the round window holds
        session.add(
            UserBlock(
                user_id=players[0],
                weekdays=1,
                start_local=time(0, 0),
                end_local=time(12, 0),
            )
        )
        player1 = session.get(User, players[0])
        assert player1 is not None
        player1.timezone = "UTC"
        session.add(player1)
        session.commit()
    return seeded


@pytest.fixture
def captain(
    client: Client,
    board_league: dict[str, Any],
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, str]:
    """P1 captains Alpha, which plays the seeded match."""
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    resp = client.put(
        f"/teams/{board_league['team_a_id']}/seasons/{board_league['season_id']}/captains",
        json={"captain_ids": [board_league["player_ids"][0]]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    stub_clerk(monkeypatch, account={"id": "1", "username": "p1", "avatar": None})
    return SESSION


def test_the_board_answers_every_figure_of_the_match(
    client: Client, board_league: dict[str, Any], captain: dict[str, str]
) -> None:
    players = board_league["player_ids"]
    resp = client.get(
        f"/matches/{board_league['match_id']}/draft-board", headers=captain
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["max_mmr_difference"] == 120
    assert body["series_per_round"] == 2
    # the seed publishes two series on the match and drafts none
    assert body["published_series"] == 2
    assert body["open_drafts"] == 0
    assert {row["user_id"] for row in body["players"]} == set(players)

    by_id = {row["user_id"]: row for row in body["players"]}
    assert by_id[players[0]]["race"] == "HU"
    assert by_id[players[0]]["mmr"] == 1500
    assert by_id[players[0]]["games"] == 40
    # twelve rows, the newest ten, newest first, alternating from a win
    assert by_id[players[0]]["form"] == "LWLWLWLWLW"
    # six wins and six losses over four opponent races
    assert by_id[players[0]]["vs_race"]["HU"] == [3, 0]
    assert by_id[players[0]]["vs_race"]["OC"] == [0, 3]
    assert by_id[players[1]]["form"] == ""
    assert by_id[players[1]]["mmr"] is None


def test_a_captain_draft_stage_with_no_setting_reads_the_default(
    client: Client, board_league: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    """A null row reads as the default, the same number the stage payload sends."""
    with Session() as session:
        stage = session.scalars(
            select(EventStage).where(
                col(EventStage.event_id) == board_league["season_id"]
            )
        ).one()
        stage.max_mmr_difference = None
        session.add(stage)
        session.commit()
    body = client.get(
        f"/matches/{board_league['match_id']}/draft-board", headers=auth_headers
    ).json()
    assert body["max_mmr_difference"] == MAX_MMR_DIFFERENCE


def test_the_games_rule_flags_too_few_games_and_no_stats(
    client: Client, board_league: dict[str, Any], captain: dict[str, str]
) -> None:
    """The event's min_games over min_games_seasons is the one rule."""
    players = board_league["player_ids"]
    with Session() as session:
        event = session.get(Season, board_league["season_id"])
        assert event is not None
        event.min_games = 20
        event.min_games_seasons = 2
        session.add(event)
        session.commit()

    body = client.get(
        f"/matches/{board_league['match_id']}/draft-board", headers=captain
    ).json()
    by_id = {row["user_id"]: row for row in body["players"]}
    assert by_id[players[0]]["games_warning"] is None
    # three games on the race, under twenty
    assert by_id[players[2]]["games_warning"] == "under_min_games"
    # no stored W3C row at all
    assert by_id[players[1]]["games_warning"] == "no_w3c_stats"


def test_a_pair_carries_hours_and_the_head_to_head_only_when_they_met(
    client: Client, board_league: dict[str, Any], captain: dict[str, str]
) -> None:
    players = board_league["player_ids"]
    body = client.get(
        f"/matches/{board_league['match_id']}/draft-board", headers=captain
    ).json()
    pairs = {(row["player1_id"], row["player2_id"]): row for row in body["pairs"]}
    # two players a side, so four pairings and no MMR difference on any of them
    assert len(pairs) == 4
    assert "mmr_difference" not in body["pairs"][0]

    met = pairs[(players[0], players[2])]
    # the seeded series is 2-1 to P1 over P3
    assert (met["wins"], met["losses"]) == (1, 0)
    assert met["last_event"] == "Season 1"

    never = pairs[(players[0], players[3])]
    assert never["wins"] is None and never["losses"] is None
    assert never["last_event"] is None

    # the round runs seven whole days; P1 blocks twelve hours of its Monday
    assert pairs[(players[1], players[3])]["hours"] == pytest.approx(7 * 24)
    assert met["hours"] == pytest.approx(7 * 24 - 12)


def test_the_head_to_head_reads_in_pairing_order_whoever_was_stored_first(
    client: Client, board_league: dict[str, Any], captain: dict[str, str]
) -> None:
    """The same 2-1 win of P1 over P3, stored with P3 as player1."""
    players = board_league["player_ids"]
    with Session() as session:
        series = session.get(Series, board_league["series_played_id"])
        assert series is not None
        series.player1_id, series.player2_id = players[2], players[0]
        series.player1_score, series.player2_score = 1, 2
        session.add(series)
        session.commit()
    body = client.get(
        f"/matches/{board_league['match_id']}/draft-board", headers=captain
    ).json()
    pairs = {(row["player1_id"], row["player2_id"]): row for row in body["pairs"]}
    met = pairs[(players[0], players[2])]
    assert (met["wins"], met["losses"]) == (1, 0)


def test_only_a_captain_of_the_match_or_an_admin_reads_the_board(
    client: Client,
    board_league: dict[str, Any],
    auth_headers: dict[str, str],
    member: Callable[..., dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = f"/matches/{board_league['match_id']}/draft-board"
    assert client.get(url).status_code == 401
    assert client.get(url, headers=member("2")).status_code == 403
    assert client.get(url, headers=auth_headers).status_code == 200


def test_a_captain_of_a_team_that_does_not_play_the_match_is_refused(
    client: Client,
    board_league: dict[str, Any],
    auth_headers: dict[str, str],
    captain: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The board is a captain's own match, not any match of the event."""
    url = f"/matches/{board_league['match_id']}/draft-board"
    assert client.get(url, headers=captain).status_code == 200

    # P2 captains Gamma, which does not play the seeded match
    stub_clerk(monkeypatch, account={"id": "2", "username": "p2", "avatar": None})
    with Session() as session:
        gamma = Team(
            name="Gamma", long_name="Team Gamma", league_id=board_league["league_id"]
        )
        session.add(gamma)
        session.commit()
        gamma_id = ident(gamma)
    resp = client.post(
        f"/seasons/{board_league['season_id']}/teams",
        json={"team_ids": [gamma_id]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    resp = client.put(
        f"/teams/{gamma_id}/seasons/{board_league['season_id']}/captains",
        json={"captain_ids": [board_league["player_ids"][1]]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text

    resp = client.get(url, headers=SESSION)
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"] == "Your team does not play this match"


def test_an_unknown_match_is_not_found(
    client: Client, board_league: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    """An admin passes the match guard, so the service answers the 404."""
    resp = client.get("/matches/9999/draft-board", headers=auth_headers)
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"] == "match_not_found"


def test_the_board_is_never_stored_in_a_shared_cache(
    client: Client, board_league: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    """A per-caller read carries private, so no edge copy is served to anyone
    else and the CORS pitfall of a public copy cannot happen."""
    resp = client.get(
        f"/matches/{board_league['match_id']}/draft-board", headers=auth_headers
    )
    assert resp.headers["cache-control"].startswith("private")
    resp = client.get(
        f"/users/{board_league['player_ids'][0]}/meetings/"
        f"{board_league['player_ids'][2]}",
        headers=auth_headers,
    )
    assert resp.headers["cache-control"].startswith("private")


def test_the_board_costs_a_constant_number_of_statements(
    client: Client, board_league: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    """The count does not grow with the rosters: a bigger match reads the same
    statements, so the board never runs a query per player or per pairing."""
    url = f"/matches/{board_league['match_id']}/draft-board"
    with count_statements() as small:
        assert client.get(url, headers=auth_headers).status_code == 200
    _grow_rosters(board_league, 6)
    with count_statements() as large:
        body = client.get(url, headers=auth_headers).json()
    assert len(body["players"]) == 16
    assert len(body["pairs"]) == 64
    assert small[0] == large[0]
    # seventeen today; the guard is that it is a constant, not that it is low
    assert large[0] <= 18, large[0]
    # a full 8 by 8 board measures about 9.7 kB of figures
    assert len(json.dumps(body)) < 12_000, len(json.dumps(body))


def test_the_meetings_read_answers_the_series_time_mmr(
    client: Client, board_league: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    players = board_league["player_ids"]
    with count_statements() as tally:
        resp = client.get(
            f"/users/{players[0]}/meetings/{players[2]}", headers=auth_headers
        )
    # one statement for the meetings and both ratings, the rest is the guard
    assert tally[0] <= 3, tally[0]
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 1
    one = rows[0]
    assert one["event_label"] == "SL - Season 1"
    assert (one["player1_score"], one["player2_score"]) == (2, 1)
    assert one["player1_race"] == "HU"
    # P1's last ladder game before the 2026-01-07 19:00 series closed at 1511
    assert one["player1_mmr"] == 1511
    assert one["player2_mmr"] is None

    # the same pair the other way round reads the scores in the path's order
    flipped = client.get(
        f"/users/{players[2]}/meetings/{players[0]}", headers=auth_headers
    ).json()
    assert (flipped[0]["player1_score"], flipped[0]["player2_score"]) == (1, 2)


def test_a_meeting_with_no_time_is_rated_against_its_round(
    client: Client, board_league: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    """A series the admins never timed still rates: the round's first day is
    the instant the ladder history is read against."""
    players = board_league["player_ids"]
    with Session() as session:
        series = session.get(Series, board_league["series_played_id"])
        assert series is not None
        series.date_time = None
        session.add(series)
        # round 1 opens the day after the twelve ladder rows of 2026-01-06
        round_one = session.scalars(
            select(DBEventRound).where(
                col(DBEventRound.season_id) == board_league["season_id"],
                col(DBEventRound.number) == 1,
            )
        ).one()
        round_one.start_date = date(2026, 1, 7)
        session.add(round_one)
        session.commit()
    rows = client.get(
        f"/users/{players[0]}/meetings/{players[2]}", headers=auth_headers
    ).json()
    # the row carries no date, and the round's first day rates it at 1511
    assert rows[0]["date_time"] is None
    assert rows[0]["player1_mmr"] == 1511


def test_the_meetings_read_needs_a_signed_in_member(
    client: Client,
    board_league: dict[str, Any],
    member: Callable[..., dict[str, str]],
) -> None:
    players = board_league["player_ids"]
    url = f"/users/{players[0]}/meetings/{players[2]}"
    assert client.get(url).status_code == 401
    assert client.get(url, headers=member("2")).status_code == 200


def test_a_pair_that_never_met_reads_empty(
    client: Client, board_league: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    players = board_league["player_ids"]
    resp = client.get(
        f"/users/{players[0]}/meetings/{players[3]}", headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json() == []


def _grow_rosters(seeded: dict[str, Any], extra: int) -> None:
    """Six more players a side, so both rosters hold eight."""
    with Session() as session:
        for index in range(extra * 2):
            user = User(
                name=f"Extra {index}",
                battleTag=f"Extra{index}#9",
                discordTag=f"extra{index}",
                discordId=f"80{index}",
                race=Race.HU,
            )
            session.add(user)
            session.flush()
            user_id = ident(user)
            team = seeded["team_a_id"] if index < extra else seeded["team_b_id"]
            session.add_all(
                [
                    DBUserTeamSeason(
                        user_id=user_id, team_id=team, season_id=seeded["season_id"]
                    ),
                    DBUserSeasonSignup(
                        user_id=user_id,
                        season_id=seeded["season_id"],
                        race=Race.HU,
                    ),
                    W3CStats(
                        user_id=user_id,
                        wc3_season=9,
                        race=Race.HU,
                        games=30,
                        mmr=1200 + index,
                    ),
                    W3CLadderMatch(
                        user_id=user_id,
                        w3c_match_id=f"x{index}",
                        wc3_season=9,
                        start_time=datetime(2026, 1, 6, 12, 0, tzinfo=UTC),
                        duration_s=600,
                        race=Race.HU,
                        opp_race=Race.OC,
                        won=True,
                        mmr_before=1200,
                        mmr_after=1210,
                    ),
                    UserBlock(
                        user_id=user_id,
                        weekdays=1 << (index % 7),
                        start_local=time(1, 0),
                        end_local=time(3, 0),
                    ),
                ]
            )
        session.commit()
