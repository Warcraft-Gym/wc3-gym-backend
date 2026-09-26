"""Pin every team answer that fills rosters against tests/data/teams_parity.json.

The seeded league gains two more playdays, written out of order so the series
ids and the playdays disagree, off races on both sides, a player with no
signup, a second season, a captain who plays in no roster of the season, and
a team entered in no season. Every route runs with and without a page.

Set UPDATE_TEAMS_SNAPSHOT=1 to write the file again, and read the diff.
"""

import json
import os
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx2 import Client

from app.core.db import Session
from app.models.base import ident
from app.models.enums import Race
from app.models.match import Match
from app.models.relationships import DBTeamSeasonCaptain, DBUserSeasonSignup
from app.models.season import Season
from app.models.series import Series
from app.models.team import Team
from app.models.team_season import DBTeamSeason
from app.models.user import User
from app.models.user_team_season import DBUserTeamSeason
from app.models.w3c_stats import W3CStats
from tests.conftest import empty_tables
from tests.seed import active, seed_league

SNAPSHOT = Path(__file__).parent / "data" / "teams_parity.json"

# Signup race per player index and season; P4 holds none in season 1
SIGNUPS = {1: (Race.HU, Race.OC, Race.NE, None), 2: (Race.UD, Race.OC, Race.HU)}


@pytest.fixture
def teams_league(app: FastAPI) -> dict[str, Any]:
    """The league of the module docstring, the same on every run.

    The tables start empty, so the ids hold whichever test ran first.
    """
    empty_tables()
    with Session() as session:
        seeded = seed_league(session)
        session.commit()
        one = seeded["season_id"]
        a, b = seeded["team_a_id"], seeded["team_b_id"]
        p1, p2, p3, p4 = seeded["player_ids"]
        p5 = User(
            name="P5",
            battle_tags=active("P5#5555"),
            discordTag="p5",
            discordId="5",
            race=Race.RANDOM,
            mmr=1700,
            country="NO",
        )
        two = Season(name="Season 2", league_id=seeded["league_id"], series_per_round=2)
        idle = Team(name="Gamma", league_id=seeded["league_id"])
        session.add_all([p5, two, idle])
        session.flush()
        players = [p1, p2, p3, p4, ident(p5)]

        for user_id in players:
            for season in range(8):
                if user_id == players[4] and season not in (2, 7):
                    continue
                session.add(
                    W3CStats(
                        user_id=user_id,
                        wc3_season=season,
                        race=Race.HU if season % 2 else Race.NE,
                        wins=season,
                        losses=season + 1,
                        games=2 * season + 1,
                        mmr=1500 + 10 * season + user_id,
                    )
                )
        for number, season_id in ((1, one), (2, ident(two))):
            for user_id, race in zip(players, SIGNUPS[number], strict=False):
                if race is not None:
                    session.add(
                        DBUserSeasonSignup(
                            user_id=user_id, season_id=season_id, race=race
                        )
                    )

        session.add_all(
            [
                DBTeamSeason(team_id=a, season_id=ident(two)),
                DBTeamSeason(team_id=b, season_id=ident(two)),
                DBUserTeamSeason(user_id=p1, team_id=a, season_id=ident(two)),
                DBUserTeamSeason(user_id=p2, team_id=a, season_id=ident(two)),
                DBUserTeamSeason(user_id=p3, team_id=b, season_id=ident(two)),
                DBUserTeamSeason(user_id=players[4], team_id=b, season_id=ident(two)),
                DBTeamSeasonCaptain(team_id=a, season_id=one, user_id=p1),
                DBTeamSeasonCaptain(team_id=b, season_id=one, user_id=players[4]),
                DBTeamSeasonCaptain(team_id=a, season_id=ident(two), user_id=p2),
            ]
        )

        # Playday 3 first, so its series ids come before the ones of playday 2
        third = Match(team1_id=b, team2_id=a, season_id=one, playday=3)
        second = Match(team1_id=a, team2_id=b, season_id=one, playday=2)
        other = Match(team1_id=a, team2_id=b, season_id=ident(two), playday=1)
        session.add_all([third, second, other])
        session.flush()

        def add(
            match: Match,
            one: int,
            two: int,
            score: tuple[int | None, int | None],
            off: tuple[Race | None, Race | None] = (None, None),
        ) -> None:
            session.add(
                Series(
                    match_id=ident(match),
                    player1_id=one,
                    player2_id=two,
                    player1_score=score[0],
                    player2_score=score[1],
                    host_player_id=one,
                    player1_off_race=off[0],
                    player2_off_race=off[1],
                )
            )

        add(third, p3, p1, (2, 0))
        add(third, p4, p2, (1, 2), (Race.HU, None))
        add(second, p1, p4, (2, 1), (Race.NE, None))
        add(second, p2, p3, (None, None), (None, Race.UD))
        add(other, p1, p3, (0, 2))
        add(other, p2, players[4], (2, 0), (None, Race.OC))
        session.commit()
        return seeded | {
            "season_two_id": ident(two),
            "idle_team_id": ident(idle),
        }


def answers(client: Client, league: dict[str, Any]) -> dict[str, Any]:
    """Every team answer the snapshot pins, status and body."""
    seasons = (league["season_id"], league["season_two_id"])
    teams = (league["team_a_id"], league["team_b_id"], league["idle_team_id"])
    paths = [
        f"/leagues/{league['league_id']}/teams",
        f"/leagues/{league['league_id']}/teams/basic",
    ]
    for season_id in seasons:
        base = f"/events/{season_id}/teams"
        paths += [
            base,
            f"{base}?limit=1",
            f"{base}?limit=1&offset=1",
            f"{base}?offset=5",
            f"{base}/basic",
        ]
        paths += [f"{base}/{team_id}" for team_id in teams]

    found = {}
    for path in paths:
        resp = client.get(path)
        found[path] = {"status": resp.status_code, "body": resp.json()}
    return found


def test_every_team_answer_matches_the_snapshot(
    client: Client, teams_league: dict[str, Any]
) -> None:
    payloads = answers(client, teams_league)
    if os.getenv("UPDATE_TEAMS_SNAPSHOT"):
        SNAPSHOT.write_text(json.dumps(payloads, indent=2) + "\n")
    # The dump keeps key order, so a field that moves fails too
    assert json.dumps(payloads) == json.dumps(json.loads(SNAPSHOT.read_text()))

