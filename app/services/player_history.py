"""What one player did in the league, derived at read time.

Six statements answer the whole page, and none of them grows with the number
of seasons or opponents: one reads every series the player stood in with its
season and its opponent, one the teams they were rostered on, one the teams
each of those seasons held, one the current season setting, and the last pair
is the score system and the points of every team, borrowed from
app.services.derived.

A series with no map score is unplayed: it pays no record and shows in no
meeting. A won series is one the player took more maps in, as the career
totals count it, so a drawn series is neither won nor lost.
"""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Row, func, select, union_all
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import aliased
from sqlmodel import col

from app.core.db import Session
from app.models.match import Match
from app.models.player_history import (
    HistoryEvent,
    HistoryMeeting,
    HistoryOpponent,
    PlayerHistory,
)
from app.models.season import Season
from app.models.series import Series
from app.models.settings import Settings
from app.models.team import Team
from app.models.team_season import DBTeamSeason
from app.models.user import User
from app.models.user_team_season import DBUserTeamSeason
from app.services import derived

# season -> the team the player was on, its name, and the season name
type Rosters = dict[int, tuple[int, str | None, str]]
# (team, season) -> where the team finished and how many teams stood
type Places = dict[tuple[int, int], tuple[int, int]]


def _meetings(session: OrmSession, user_id: int) -> Sequence[Row[Any]]:
    """Every series the player stood in, newest first, in one statement.

    A series holds the player on either side, so the two sides union and the
    other side is the opponent.
    """
    opponent1, opponent2 = aliased(User), aliased(User)
    sides = union_all(
        select(
            col(Series.id).label("series_id"),
            col(Match.season_id).label("season_id"),
            col(Match.playday).label("playday"),
            col(Series.date_time).label("date_time"),
            func.coalesce(Series.player1_score, 0).label("own"),
            func.coalesce(Series.player2_score, 0).label("opp"),
            col(opponent1.id).label("opponent_id"),
            col(opponent1.name).label("opponent_name"),
            col(opponent1.race).label("race"),
            col(opponent1.country).label("country"),
        )
        .join(Match, col(Match.id) == Series.match_id)
        .join(opponent1, col(opponent1.id) == Series.player2_id)
        .where(col(Series.player1_id) == user_id),
        select(
            col(Series.id),
            col(Match.season_id),
            col(Match.playday),
            col(Series.date_time),
            func.coalesce(Series.player2_score, 0),
            func.coalesce(Series.player1_score, 0),
            col(opponent2.id),
            col(opponent2.name),
            col(opponent2.race),
            col(opponent2.country),
        )
        .join(Match, col(Match.id) == Series.match_id)
        .join(opponent2, col(opponent2.id) == Series.player1_id)
        .where(col(Series.player2_id) == user_id),
    ).subquery()

    return session.execute(
        select(sides, col(Season.name).label("season_name"))
        .join(Season, col(Season.id) == sides.c.season_id)
        .order_by(
            sides.c.season_id.desc(), sides.c.playday.desc(), sides.c.series_id.desc()
        )
    ).all()


def _rosters(session: OrmSession, user_id: int) -> Rosters:
    """The team the player was rostered on in every season, in one statement."""
    rows = session.execute(
        select(
            col(DBUserTeamSeason.season_id),
            col(DBUserTeamSeason.team_id),
            col(Team.name),
            col(Season.name),
        )
        .join(Team, col(Team.id) == DBUserTeamSeason.team_id)
        .join(Season, col(Season.id) == DBUserTeamSeason.season_id)
        .where(col(DBUserTeamSeason.user_id) == user_id)
    ).all()
    return {
        season_id: (team_id, team_name, season_name)
        for season_id, team_id, team_name, season_name in rows
    }


def _places(session: OrmSession, season_ids: set[int]) -> Places:
    """Where every team of those seasons finished, by the points it scored.

    Teams that scored the same share a place, and the next team takes the one
    after. A season no team has scored in yet stands nowhere, so it answers
    nothing rather than a made-up first place.
    """
    rules = derived._rules_by_season(session, season_ids)
    sums = derived._sums_by_team(session, rules)
    rows = session.execute(
        select(col(DBTeamSeason.season_id), col(DBTeamSeason.team_id)).where(
            col(DBTeamSeason.season_id).in_(season_ids)
        )
    ).all()

    by_season: dict[int, list[int]] = {}
    for season_id, team_id in rows:
        by_season.setdefault(season_id, []).append(team_id)

    places: Places = {}
    for season_id, team_ids in by_season.items():
        scores = {
            team_id: sums.get((team_id, season_id), [0, 0])[0] for team_id in team_ids
        }
        if not any(scores.values()):
            continue
        for team_id, score in scores.items():
            ahead = sum(1 for other in scores.values() if other > score)
            places[(team_id, season_id)] = (ahead + 1, len(team_ids))
    return places


def _events(
    rows: Sequence[Row[Any]],
    rosters: Rosters,
    places: Places,
    current_id: int | None,
) -> list[HistoryEvent]:
    """One row per season the player was rostered in or played a series in."""
    names = {season_id: name for season_id, (_, _, name) in rosters.items()}
    names |= {row.season_id: row.season_name for row in rows}

    tallies: dict[int, list[int]] = {}
    for row in rows:
        if row.own == 0 and row.opp == 0:
            continue
        tally = tallies.setdefault(row.season_id, [0, 0, 0])
        tally[0] += 1
        if row.own > row.opp:
            tally[1] += 1
        elif row.opp > row.own:
            tally[2] += 1

    events = []
    for season_id in sorted(names, reverse=True):
        team_id, team_name, _ = rosters.get(season_id, (None, None, None))
        played, won, lost = tallies.get(season_id, [0, 0, 0])
        place, team_count = places.get((team_id, season_id), (None, None))
        events.append(
            HistoryEvent(
                season_id=season_id,
                season_name=names[season_id],
                team_id=team_id,
                team_name=team_name,
                played=played,
                won=won,
                lost=lost,
                place=place,
                team_count=team_count,
                running=season_id == current_id,
            )
        )
    return events


def _opponents(rows: Sequence[Row[Any]]) -> list[HistoryOpponent]:
    """One row per opponent the player ever played, most met first.

    The rows arrive newest first, so the first one an opponent shows in is the
    last time the two met.
    """
    opponents: dict[int, HistoryOpponent] = {}
    for row in rows:
        if row.own == 0 and row.opp == 0:
            continue
        opponent = opponents.get(row.opponent_id)
        if opponent is None:
            opponent = opponents[row.opponent_id] = HistoryOpponent(
                id=row.opponent_id,
                name=row.opponent_name,
                race=row.race.value if row.race else None,
                country=row.country,
                played=0,
                won=0,
                lost=0,
                last_season_name=row.season_name,
                last_playday=row.playday,
                meetings=[],
            )
        opponent.played += 1
        if row.own > row.opp:
            opponent.won += 1
        elif row.opp > row.own:
            opponent.lost += 1
        opponent.meetings.append(
            HistoryMeeting(
                series_id=row.series_id,
                season_id=row.season_id,
                season_name=row.season_name,
                playday=row.playday,
                my_score=row.own,
                their_score=row.opp,
                date_time=row.date_time,
            )
        )
    return sorted(opponents.values(), key=lambda one: (-one.played, one.name or ""))


def history(user_id: int) -> PlayerHistory:
    """Every season the player took part in, and every opponent they ever met."""
    with Session.begin() as session:
        rows = _meetings(session, user_id)
        rosters = _rosters(session, user_id)
        season_ids = {row.season_id for row in rows} | set(rosters)
        current = Settings.get_by_key(session, "current_gnl_season")
        value = current.value if current else None
        return PlayerHistory(
            events=_events(
                rows,
                rosters,
                _places(session, season_ids),
                int(value) if value and value.isdigit() else None,
            ),
            opponents=_opponents(rows),
        )
