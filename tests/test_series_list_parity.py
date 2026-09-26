"""Pin every season series list against tests/data/series_list_parity.json.

The league holds two seasons. The first plays on the default rules and holds
a stage whose round overrides the best-of: a fixture of that round carries
series that name team entrants (a stage series), one that names no entrant,
and the stage's round also holds a series of its own with no fixture. The
second season names its own map rules and the helpstone score system. Series
carry full vetoes, a veto with one pick, a veto with bans only, and none.

Every answer is kept as the exact bytes the route or the service sends.
Set UPDATE_SERIES_SNAPSHOT=1 to write the file again, and read the diff.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from httpx2 import Client

from app.core.db import Session
from app.core.query import QueryUtil
from app.models.base import ident
from app.models.enums import Race
from app.models.event_entrant import EventEntrant
from app.models.event_stage import EventStage
from app.models.league import League
from app.models.map import Map
from app.models.match import Match
from app.models.relationships import DBEventRound, DBUserSeasonSignup
from app.models.season import Season
from app.models.series import Series
from app.models.series_veto_step import DBSeriesVetoStep
from app.models.team import Team
from app.models.user import User
from app.models.w3c_stats import W3CStats
from app.services.series import SeriesService
from tests.seed import active

SNAPSHOT = Path(__file__).parent / "data" / "series_list_parity.json"

NAMES = ("Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot")

# side, action and map index of each step; a full veto bans two and picks two
FULL_VETO = (("A", "ban", 0), ("B", "ban", 1), ("A", "pick", 2), ("B", "pick", 3))
ONE_PICK = (("A", "ban", 0), ("B", "ban", 1), ("B", "pick", 2))
BANS_ONLY = (("A", "ban", 3), ("B", "ban", 2))


@pytest.fixture
def two_seasons() -> dict[str, int]:
    """The league of the module docstring, the same on every run."""
    with Session() as session:
        # A fixed id: the migration seeds leagues only the first test sees
        owner = League(id=10, name="Series Parity League")
        session.add(owner)
        session.flush()
        users = [
            User(
                name=name,
                battle_tags=active(f"{name}#{2000 + number}"),
                discordTag=name.lower(),
                discordId=str(200 + number),
                race=Race.HU,
                mmr=1600 + number,
            )
            for number, name in enumerate(NAMES)
        ]
        maps = [Map(name=f"Map {n}", shortname=f"m{n}") for n in range(4)]
        plain = Season(name="Plain", league_id=ident(owner), series_per_round=2)
        priced = Season(
            name="Priced",
            league_id=ident(owner),
            series_per_round=2,
            map_rules="veto,veto,loser,loser,host",
            score_system="helpstone",
        )
        teams = [Team(name=f"P{n}", league_id=ident(owner)) for n in range(2)]
        session.add_all([*users, *maps, plain, priced, *teams])
        session.flush()
        uid = [ident(user) for user in users]
        for user_id, race in zip(uid, (Race.HU, Race.OC, Race.NE, Race.UD) * 2):
            for season in (plain, priced):
                session.add(
                    DBUserSeasonSignup(
                        user_id=user_id, season_id=ident(season), race=race
                    )
                )
            session.add(
                W3CStats(
                    user_id=user_id,
                    wc3_season=20,
                    race=race,
                    wins=5,
                    losses=3,
                    games=8,
                    mmr=1700 + user_id,
                )
            )

        stage = EventStage(
            event_id=ident(plain), best_of=5, map_rules="veto,veto,loser,loser,loser"
        )
        session.add(stage)
        session.flush()
        stage_round = DBEventRound(
            stage_id=ident(stage), season_id=ident(plain), number=2, best_of=7
        )
        plain_round = DBEventRound(season_id=ident(plain), number=1)
        entrants = [
            EventEntrant(event_id=ident(plain), team_id=ident(team)) for team in teams
        ]
        session.add_all([stage_round, plain_round, *entrants])
        session.flush()

        def fixture(season: Season, playday: int) -> Match:
            match = Match(
                team1_id=ident(teams[0]),
                team2_id=ident(teams[1]),
                season_id=ident(season),
                playday=playday,
                fixed_map_id=ident(maps[0]),
            )
            session.add(match)
            session.flush()
            return match

        def add(
            match: Match | None,
            one: int | None,
            two: int | None,
            score: tuple[int | None, int | None],
            veto: tuple[tuple[str, str, int], ...] = (),
            **extra: Any,  # noqa: ANN401
        ) -> None:
            row = Series(
                match_id=ident(match) if match else None,
                date_time=datetime(2026, 2, 3, 19, len(veto)),
                player1_id=uid[one] if one is not None else None,
                player2_id=uid[two] if two is not None else None,
                player1_score=score[0],
                player2_score=score[1],
                host_player_id=uid[one] if one is not None else 0,
                **extra,
            )
            session.add(row)
            session.flush()
            for step_no, (side, action, map_index) in enumerate(veto, start=1):
                session.add(
                    DBSeriesVetoStep(
                        series_id=ident(row),
                        step_no=step_no,
                        side=side,
                        action=action,
                        map_id=ident(maps[map_index]),
                    )
                )

        week1 = fixture(plain, 1)
        add(week1, 0, 1, (2, 1), FULL_VETO, round_id=ident(plain_round))
        add(week1, 2, 3, (0, 2), ONE_PICK, player2_off_race=Race.OC)
        add(week1, 4, 5, (None, None), BANS_ONLY)
        add(week1, 1, 2, (2, 0), is_fantasy_match=True)

        week2 = fixture(plain, 2)
        entrant1, entrant2 = (ident(entrant) for entrant in entrants)
        add(
            week2,
            0,
            2,
            (3, 1),
            FULL_VETO,
            round_id=ident(stage_round),
            entrant1_id=entrant1,
            entrant2_id=entrant2,
        )
        add(
            week2,
            None,
            None,
            (None, None),
            round_id=ident(stage_round),
            entrant1_id=entrant1,
            entrant2_id=entrant2,
            side_size=2,
        )
        add(week2, 3, 5, (1, 2), ONE_PICK, round_id=ident(stage_round))
        # The stage's own series, with no fixture, is in no season list
        add(
            None,
            1,
            4,
            (2, 0),
            round_id=ident(stage_round),
            entrant1_id=entrant1,
            entrant2_id=entrant2,
        )

        for playday in (1, 2):
            match = fixture(priced, playday)
            add(match, 0, 3, (3, 0), FULL_VETO)
            add(match, 1, 4, (2, 3), ONE_PICK, player1_off_race=Race.NE)
            add(match, 2, 5, (None, None))
        session.commit()
        return {"plain": ident(plain), "priced": ident(priced), "user": uid[1]}


PAGES = ("", "?limit=1", "?limit=3&offset=2", "?offset=5", "?limit=500&offset=100")
SEARCHES = ("", "player1_id > 0", "is_fantasy_match == True", "player1_score == 3")
SORTS = (None, "date_time", "week", "id")


def answers(client: Client, league: dict[str, int]) -> dict[str, Any]:
    """Every season list answer the snapshot pins, as the text sent."""
    found: dict[str, Any] = {}
    for season in ("plain", "priced"):
        event_id = league[season]
        for page in PAGES:
            resp = client.get(f"/events/{event_id}/series{page}")
            assert resp.status_code == 200
            found[f"GET {season} {page}"] = resp.text
        for search in SEARCHES:
            resp = client.post(
                f"/events/{event_id}/series/search", params={"query": search}
            )
            assert resp.status_code == 200
            found[f"POST {season} {search!r}"] = resp.text

    service = SeriesService()
    mine = QueryUtil.parse_query(
        f"player1_id == {league['user']} or player2_id == {league['user']}"
    )
    for season in ("plain", "priced"):
        for sort in SORTS:
            for order in ("asc", "desc"):
                rows = service.search_for_season(
                    league[season], mine, sort=sort, order=order
                )
                found[f"service {season} {sort} {order}"] = [
                    row.model_dump_json() for row in rows
                ]
    return found


def test_every_season_series_answer_matches_the_snapshot(
    client: Client, two_seasons: dict[str, int]
) -> None:
    payloads = answers(client, two_seasons)
    if os.getenv("UPDATE_SERIES_SNAPSHOT"):
        SNAPSHOT.write_text(json.dumps(payloads, indent=2, sort_keys=True) + "\n")
    assert payloads == json.loads(SNAPSHOT.read_text())
