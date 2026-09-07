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
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core import ladder
from app.core.achievements import (
    ACHIEVEMENTS,
    ELITE_MMR,
    LADDER_MAPS,
    NEW_MAPS,
    TEAM_IDS,
    WINTER_MAPS,
    Achievement,
    priced_id,
)
from app.core.db import Session
from app.models.enums import Race
from app.models.relationships import DBTeamSeasonCaptain
from app.models.season import Season
from app.models.w3c_ladder_match import W3CLadderMatch
from app.services.ladder import (
    LadderService,
    _any_race,
    _context,
    _paid,
    _roster,
    _scope,
    _window,
)
from tests import achievement_oracle
from tests.achievement_oracle import Season as OracleSeason
from tests.test_ladder_read import sign_up

# How many rounds of matches the two rule sets are compared over
ROUNDS = 60
# The window opens here; the season the seed writes runs from 2026-01-05
START = datetime(2026, 1, 6, 0, 0, tzinfo=UTC)
# A short pool of days, so one day collects enough matches to addict a player,
# and the whole window for the rules that read weeks
DAYS = 8
WINDOW_DAYS = 53
# Maps in the sets, one outside every set, and none at all
MAPS = (*LADDER_MAPS, *WINTER_MAPS, *NEW_MAPS, "Twisted Meadows", None)
# 120 seconds and less is no game, 1800 is not a long one and 1801 is
DURATIONS = (60, 120, 121, 480, 600, 1800, 1801, 2400, 2700, 3000)
# Nobody on the roster, so a win over one of these is no kill
STRANGERS = (*(f"Stranger#{n:04d}" for n in range(24)), None)
# Rules the random rounds are not expected to reach; each has its own test
RARE = {"open_season"}  # five distinct members beaten: the seed has four players


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

        expected = _oracle(season_id)
        assert found == expected, f"round {seed}: {_diff(found, expected)}"
        seen |= {priced_id(badge.id) for badges in found.values() for badge in badges}

    # A rule no round earns is a rule this test does not compare; the team
    # rules pay a team, which this test does not read
    wanted = {rule.id for rule in ACHIEVEMENTS if rule.id not in TEAM_IDS} - RARE
    assert seen >= wanted, f"never earned: {sorted(wanted - seen)}"


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
                days=rng.randrange(WINDOW_DAYS if rng.random() < 0.3 else DAYS),
                hours=rng.randrange(24),
                seconds=rng.randrange(3600),
            )
        rated = rng.random() < 0.9
        before = mmr
        mmr += rng.choice((-60, -45, -30, 0, 30, 45, 60))
        after = ELITE_MMR if rng.random() < 0.05 else mmr
        race = player.race if rng.random() < 0.85 else rng.choice([*Race])
        opp_race = rng.choice([*Race, None])
        rows.append(
            {
                "w3c_match_id": f"{player.user_id}-{index}",
                "user_id": player.user_id,
                "wc3_season": 25,
                "start_time": start,
                "duration_s": rng.choice(DURATIONS),
                "map_name": rng.choice(MAPS),
                "race": race,
                "played_race": _rolled(rng, race),
                "opp_battletag": rng.choice([*tags, *STRANGERS]),
                "opp_race": opp_race,
                "opp_played_race": _rolled(rng, opp_race),
                "won": won,
                "mmr_before": before if rated else None,
                "mmr_after": after if rated else None,
            }
        )
        mmr = after
    return rows


def _rolled(rng: random.Random, race: Race | None) -> Race | None:
    """The race played: a Random pick rolls one of the four, mostly."""
    if race is Race.RANDOM and rng.random() < 0.9:
        return rng.choice([r for r in Race if r is not Race.RANDOM])
    return race


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
        season = session.get_one(Season, season_id)
        roster = _roster(session, season_id)
        user_ids = [row.user_id for row in roster]
        window = _window(season)
        matches = _by_player(session, user_ids, _scope(user_ids, window, season_id))
        every_race = _by_player(session, user_ids, _any_race(user_ids, window))
        ctx = _context(session, roster, season, {})
        team_of_tag = {tag: team for team, tags in ctx.tags.items() for tag in tags}
        own_team = {user: team for team, users in ctx.teams.items() for user in users}
        # The season-wide race: the earliest 50th game, ties to the lowest id
        fifty = [
            (rows[49].start_time, user_id)
            for user_id, rows in matches.items()
            if len(rows) >= 50
        ]
        first_fifty = min(fifty)[1] if fifty else None
        paid, _ = _paid(session, season_id)
        return {
            row.user_id: achievement_oracle.earned(
                matches[row.user_id],
                ladder.totals(matches[row.user_id]).points,
                paid,
                ctx.opponents.get(row.user_id, frozenset()),
                ctx.captains,
                (row.battleTag or "").lower() in ctx.captains,
                OracleSeason(
                    window=window,
                    pool=ctx.pool,
                    opponents=ctx.opponents.get(row.user_id, frozenset()),
                    teammates=ctx.teammates.get(row.user_id, frozenset()),
                    members=ctx.members,
                    team_of_tag=team_of_tag,
                    own_team=own_team.get(row.user_id),
                    teams=len(ctx.tags),
                    league_race=row.race.value if row.race else None,
                    all_rows=every_race[row.user_id],
                    is_first_to_fifty=row.user_id == first_fifty,
                ),
            )
            for row in roster
        }


def _diff(
    found: dict[int, list[Achievement]], expected: dict[int, list[Achievement]]
) -> str:
    """The badges one side has and the other has not, per player."""
    lines = []
    for user_id in sorted(set(found) | set(expected)):
        sql = {(b.id, b.achieved_at, b.points) for b in found.get(user_id, [])}
        oracle = {(b.id, b.achieved_at, b.points) for b in expected.get(user_id, [])}
        if sql != oracle:
            lines.append(
                f"player {user_id}: sql only {sorted(sql - oracle)}; oracle only {sorted(oracle - sql)}"
            )
        elif found.get(user_id, []) != expected.get(user_id, []):
            lines.append(f"player {user_id}: same badges, different order")
    return "\n".join(lines)


def _by_player(
    session: OrmSession, user_ids: list[int], scope: list[Any]
) -> dict[int, list[W3CLadderMatch]]:
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
    return matches
