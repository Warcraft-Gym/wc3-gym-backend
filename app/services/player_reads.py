"""A player's seasons and series, computed in SQL from his side.

The seasons read costs three statements: one for his roster and captain seats
with their team and his signup, and the season record pair of
app.services.derived. The series read costs two: one for the page of series as
columns with its total, and one for their casts. Neither grows with the number
of seasons or series.

Each statement is built once per process, with bound parameters for the values
of a call: building one costs more Python time than running it.
"""

from collections.abc import Sequence
from functools import cache
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Integer,
    Row,
    Select,
    bindparam,
    case,
    func,
    literal,
    select,
    union_all,
)
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.selectable import Subquery
from sqlmodel import col

from app.core.db import Session
from app.core.fantasy import race_value
from app.models.match import Match
from app.models.player_reads import (
    PlayerSeasonPublic,
    PlayerSeasonRecordPublic,
    PlayerSeriesSummaryPublic,
)
from app.models.relationships import DBTeamSeasonCaptain, DBUserSeasonSignup
from app.models.season import Season
from app.models.series import Series
from app.models.series_cast import SeriesCast, channel_name, is_video_url
from app.models.team import Team
from app.models.team_summary import TeamSummaryPublic
from app.models.user import User
from app.models.user_team_season import DBUserTeamSeason
from app.services import derived


@cache
def _seats_statement() -> Select[Any]:
    """Every roster and captain seat of the player `user_id` with its team and his
    signup, newest season first, a season's roster seat before its captain seat."""
    user_id = bindparam("user_id", type_=Integer)
    seats = union_all(
        select(
            col(DBUserTeamSeason.season_id).label("season_id"),
            col(DBUserTeamSeason.team_id).label("team_id"),
            literal(1, Integer).label("roster"),
        ).where(col(DBUserTeamSeason.user_id) == user_id),
        select(
            col(DBTeamSeasonCaptain.season_id),
            col(DBTeamSeasonCaptain.team_id),
            literal(0, Integer),
        ).where(col(DBTeamSeasonCaptain.user_id) == user_id),
    ).subquery()
    signup = aliased(DBUserSeasonSignup)
    return (
        select(
            seats.c.season_id,
            seats.c.roster,
            col(Team.id).label("team_id"),
            col(Team.league_id),
            col(Team.name),
            col(Team.long_name),
            col(Team.icon_url),
            col(signup.race).label("race"),
            col(signup.played_as).label("played_as"),
        )
        .join(Season, col(Season.id) == seats.c.season_id)
        .join(Team, col(Team.id) == seats.c.team_id)
        .join(
            signup,
            (col(signup.user_id) == user_id)
            & (col(signup.season_id) == seats.c.season_id),
            isouter=True,
        )
        .order_by(
            col(Season.start_date).desc().nulls_last(),
            col(Season.id).desc(),
            seats.c.roster.desc(),
            seats.c.team_id,
        )
    )


def seasons(user_id: int) -> list[PlayerSeasonPublic]:
    """One row per season the player held a roster or a captain seat in."""
    with Session.begin() as session:
        rows = session.execute(_seats_statement(), {"user_id": user_id}).all()
        if not rows:
            return []
        by_season: dict[int, list[Row[Any]]] = {}
        for row in rows:
            by_season.setdefault(row.season_id, []).append(row)
        tallies = derived._gnl_tallies(session, {user_id}, set(by_season))
        matchups = derived._gnl_matchups(session, {user_id}, set(by_season))

    answer = []
    for season_id, seats in by_season.items():
        seat = seats[0]
        captained = {row.team_id for row in seats if not row.roster}
        tally = tallies.get((user_id, season_id), derived.GnlTally(0, 0, 0))
        answer.append(
            PlayerSeasonPublic(
                season_id=season_id,
                team=TeamSummaryPublic(
                    id=seat.team_id,
                    league_id=seat.league_id,
                    name=seat.name,
                    long_name=seat.long_name,
                    icon_url=seat.icon_url,
                ),
                is_captain=seat.team_id in captained,
                captain_only=not seat.roster,
                signup_race=race_value(seat.race),
                played_as=seat.played_as,
                record=PlayerSeasonRecordPublic(
                    games=tally.games,
                    wins=tally.wins,
                    losses=tally.losses,
                    matchup_history=matchups.get((user_id, season_id), []),
                ),
            )
        )
    return answer


def _team_name(team: type[Team]) -> ColumnElement[Any]:
    """The long name of a team when it has one, else its name."""
    return case(
        (func.coalesce(col(team.long_name), "") != "", col(team.long_name)),
        else_=col(team.name),
    )


def _sides() -> Subquery:
    """The GNL series of the player `user_id` in the events `event_ids`, one row
    each from his side."""
    user_id = bindparam("user_id", type_=Integer)
    event_ids = bindparam("event_ids", expanding=True)
    one = (
        col(Series.player1_id),
        col(Series.player1_score),
        col(Series.player1_off_race),
    )
    two = (
        col(Series.player2_id),
        col(Series.player2_score),
        col(Series.player2_off_race),
    )
    parts = []
    for mine, theirs in ((one, two), (two, one)):
        my_id, my_score, my_off = mine
        their_id, their_score, their_off = theirs
        my_signup, their_signup = (
            aliased(DBUserSeasonSignup),
            aliased(DBUserSeasonSignup),
        )
        opponent = aliased(User)
        parts.append(
            select(
                col(Series.id).label("id"),
                col(Match.season_id).label("season_id"),
                col(Match.playday).label("week"),
                col(Series.date_time).label("date_time"),
                derived.race_of(my_off, my_signup).label("race"),
                my_score.label("score"),
                their_score.label("opponent_score"),
                their_id.label("opponent_id"),
                col(opponent.name).label("opponent_name"),
                derived.race_of(their_off, their_signup).label("opponent_race"),
                col(Match.team1_id).label("team1_id"),
                col(Match.team2_id).label("team2_id"),
            )
            .join(Match, col(Match.id) == Series.match_id)
            .join(opponent, col(opponent.id) == their_id, isouter=True)
            .join(my_signup, derived.signup_on(my_signup, my_id), isouter=True)
            .join(their_signup, derived.signup_on(their_signup, their_id), isouter=True)
            .where(my_id == user_id, col(Match.season_id).in_(event_ids))
        )
    return union_all(*parts).subquery("side")


@cache
def _casts_statement() -> Select[Any]:
    """Every cast of the series `series_ids` with its caster's name, by id."""
    return (
        select(
            col(SeriesCast.id),
            col(SeriesCast.series_id),
            col(SeriesCast.channel_url),
            col(SeriesCast.vod_url),
            col(User.name),
        )
        .join(User, col(User.id) == SeriesCast.user_id, isouter=True)
        .where(col(SeriesCast.series_id).in_(bindparam("series_ids", expanding=True)))
        .order_by(col(SeriesCast.id))
    )


def _first_casts(
    session: OrmSession, rows: list[PlayerSeriesSummaryPublic]
) -> dict[int, tuple[int, str, str, str | None]]:
    """The cast each series shows, as CastPublic names it: the first by id with
    a VOD, else the first."""
    if not rows:
        return {}
    scored = {
        row.id
        for row in rows
        if row.score is not None or row.opponent_score is not None
    }
    casts = session.execute(
        _casts_statement(), {"series_ids": [row.id for row in rows]}
    ).all()
    chosen: dict[int, tuple[int, str, str, str | None]] = {}
    for cast_id, series_id, channel, vod, name in casts:
        video = channel if series_id in scored and is_video_url(channel) else None
        found = (cast_id, name or channel_name(channel), channel, vod or video)
        if series_id not in chosen or (found[3] and not chosen[series_id][3]):
            chosen[series_id] = found
    return chosen


@cache
def _series_statements() -> tuple[Select[Any], Select[Any]]:
    """The page `limit`, `offset` of the player's series with their total, and
    the count alone."""
    side = _sides()
    team1, team2 = aliased(Team), aliased(Team)
    page = (
        select(
            side,
            _team_name(team1).label("team1_name"),
            _team_name(team2).label("team2_name"),
            func.count().over().label("total"),
        )
        .join(team1, col(team1.id) == side.c.team1_id, isouter=True)
        .join(team2, col(team2.id) == side.c.team2_id, isouter=True)
        .order_by(
            side.c.season_id,
            side.c.week.nulls_last(),
            side.c.date_time.nulls_last(),
            side.c.id,
        )
        .limit(bindparam("limit", type_=Integer))
        .offset(bindparam("offset", type_=Integer))
    )
    return page, select(func.count()).select_from(side)


def series(
    user_id: int, event_ids: Sequence[int], limit: int = 500, offset: int = 0
) -> tuple[list[PlayerSeriesSummaryPublic], int]:
    """One page of the player's GNL series in those events, and their count."""
    page, count = _series_statements()
    player = {"user_id": user_id, "event_ids": list(event_ids)}
    with Session.begin() as session:
        found = session.execute(
            page, {**player, "limit": limit, "offset": offset}
        ).all()
        if found:
            total = found[0].total
        elif offset:
            # A page past the end holds no row to carry the count
            total = session.scalar(count, player)
        else:
            total = 0
        rows = [
            PlayerSeriesSummaryPublic(
                id=row.id,
                season_id=row.season_id,
                week=row.week,
                date_time=row.date_time,
                race=race_value(row.race),
                score=row.score,
                opponent_score=row.opponent_score,
                opponent_id=row.opponent_id,
                opponent_name=row.opponent_name,
                opponent_race=race_value(row.opponent_race),
                team1_name=row.team1_name,
                team2_name=row.team2_name,
            )
            for row in found
        ]
        casts = _first_casts(session, rows)
    for row in rows:
        if row.id in casts:
            row.cast_id, row.cast_name, row.cast_channel_url, row.cast_vod_url = casts[
                row.id
            ]
    return rows, total or 0
