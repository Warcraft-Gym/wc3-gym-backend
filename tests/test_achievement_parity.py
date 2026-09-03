"""The rules in SQL against the same rules in Python, over random matches.

core.achievement_rules answers the badges from the database and
tests/achievement_oracle.py is the rule set the SQL replaced. Each round
writes a fresh set of matches for the whole roster, reads the season ladder
the route reads, and compares it badge by badge with the oracle over the same
stored rows.

The generator aims at every boundary the rules turn on: runs of one result
past ten, a hundred wins and a hundred losses, days of thirty matches, MMR
that lands on 1337 and moves more than 100 in a day, games over thirty
minutes, maps from every set and outside them, opponents on the other team
and captains among them, and matches that share a start time so the tie
between two badges of one instant is read too.
"""

import random
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Row, delete, insert, select
from sqlmodel import col

from app.core import ladder
from app.core.achievements import (
    ACHIEVEMENTS,
    ELITE_MMR,
    LADDER_MAPS,
    NEW_MAPS,
    WINTER_MAPS,
    Achievement,
)
from app.core.db import Session
from app.models.enums import Race
from app.models.relationships import DBTeamSeasonCaptain
from app.models.season import Season
from app.models.w3c_ladder_match import W3CLadderMatch
from app.services.ladder import (
    LadderService,
    _captain_tags,
    _opponents,
    _paid,
    _roster,
    _scope,
    _window,
)
from tests import achievement_oracle
from tests.test_ladder_read import sign_up

# How many rounds of matches the two rule sets are compared over
ROUNDS = 60
# The window opens here; the season the seed writes runs from 2026-01-05
START = datetime(2026, 1, 6, 0, 0, tzinfo=UTC)
# A short pool of days, so one day collects enough matches to addict a player
DAYS = 8
# Maps in the sets, one outside every set, and none at all
MAPS = (*LADDER_MAPS, *WINTER_MAPS, *NEW_MAPS, "Twisted Meadows", None)
# 120 seconds and less is no game, 1800 is not a long one and 1801 is
DURATIONS = (60, 120, 121, 600, 1800, 1801, 2400)
# Nobody on the roster, so a win over one of these is no kill
STRANGERS = ("Stranger#1234", "Nobody#4321", None)


@pytest.fixture
def league(seeded: dict[str, Any]) -> dict[str, Any]:
    """The seeded league, signed up, with one player captaining his team."""
    sign_up(seeded["season_id"], seeded["player_ids"])
    with Session() as session:
        session.add(
            DBTeamSeasonCaptain(
                team_id=seeded["team_b_id"],
                season_id=seeded["season_id"],
                user_id=seeded["player_ids"][2],
            )
        )
        session.commit()
    return seeded


def test_the_statement_answers_what_the_oracle_answers(league: dict[str, Any]) -> None:
    """Every badge of every player, over every round, is the same badge."""
    season_id = league["season_id"]
    service = LadderService()
    seen: set[str] = set()
    for seed in range(ROUNDS):
        _store(random.Random(seed), season_id)

        answer = service.season_ladder(season_id)
        found = {
            player.id: player.achievements
            for team in answer.teams
            for player in team.players
        }

        assert found == _oracle(season_id), f"round {seed}"
        seen |= {badge.id for badges in found.values() for badge in badges}

    # A rule no round earns is a rule this test does not compare
    assert seen == {rule.id for rule in ACHIEVEMENTS}


def _store(rng: random.Random, season_id: int) -> None:
    """Replace the stored matches with a round of random ones."""
    with Session() as session:
        roster = _roster(session, season_id)
        tags = [row.battleTag for row in roster if row.battleTag]
        rows = [
            row
            for player in roster
            for row in _matches(rng, player, tags, rng.choice((15, 60, 150, 900)))
        ]
        session.execute(delete(W3CLadderMatch))
        session.execute(insert(W3CLadderMatch), rows)
        session.commit()


def _matches(
    rng: random.Random, player: Row, tags: list[str], count: int
) -> list[dict[str, Any]]:
    """One player's matches, unordered, so the ids do not follow the clock."""
    rows: list[dict[str, Any]] = []
    mmr = 1300
    start = START
    for index, won in enumerate(_results(rng, count)):
        if rng.random() < 0.9:
            start = START + timedelta(
                days=rng.randrange(DAYS),
                hours=rng.randrange(24),
                seconds=rng.randrange(3600),
            )
        rated = rng.random() < 0.9
        before = mmr
        mmr += rng.choice((-60, -45, -30, 0, 30, 45, 60))
        after = ELITE_MMR if rng.random() < 0.05 else mmr
        rows.append(
            {
                "w3c_match_id": f"{player.user_id}-{index}",
                "user_id": player.user_id,
                "wc3_season": 25,
                "start_time": start,
                "duration_s": rng.choice(DURATIONS),
                "map_name": rng.choice(MAPS),
                "race": player.race if rng.random() < 0.92 else Race.RANDOM,
                "opp_battletag": rng.choice([*tags, *STRANGERS]),
                "opp_race": rng.choice([*Race, None]),
                "won": won,
                "mmr_before": before if rated else None,
                "mmr_after": after if rated else None,
            }
        )
        mmr = after
    return rows


def _results(rng: random.Random, count: int) -> list[bool]:
    """Wins and losses, with runs long enough to earn a streak."""
    results: list[bool] = []
    while len(results) < count:
        if rng.random() < 0.15:
            results += [rng.random() < 0.5] * rng.randrange(5, 13)
        else:
            results.append(rng.random() < 0.5)
    return results[:count]


def _oracle(season_id: int) -> dict[int, list[Achievement]]:
    """What the Python rules earn over the same stored rows."""
    with Session() as session:
        roster = _roster(session, season_id)
        user_ids = [row.user_id for row in roster]
        scope = _scope(user_ids, _window(session.get_one(Season, season_id)), season_id)
        matches: dict[int, list[W3CLadderMatch]] = {user_id: [] for user_id in user_ids}
        for row in session.scalars(
            select(W3CLadderMatch)
            .where(*scope)
            .order_by(
                col(W3CLadderMatch.user_id),
                col(W3CLadderMatch.start_time),
                col(W3CLadderMatch.id),
            )
        ):
            matches[row.user_id].append(row)
        opponents = _opponents(roster)
        captains = _captain_tags(session, season_id)
        paid = _paid(session, season_id)
        return {
            row.user_id: achievement_oracle.earned(
                matches[row.user_id],
                ladder.totals(matches[row.user_id]).points,
                paid,
                opponents.get(row.user_id, frozenset()),
                captains,
                (row.battleTag or "").lower() in captains,
            )
            for row in roster
        }
