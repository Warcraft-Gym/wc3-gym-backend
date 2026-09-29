"""An event's fixture series as list rows, computed in SQL.

The read costs three statements beside the event phase the route reads for its
cache: the season's score system and map rules, the page of series as columns,
and the casts of that page. None grows with the number of series.
"""

from typing import Any

from sqlalchemy import ColumnElement, Row, func, or_, select
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import aliased
from sqlmodel import col

from app.core.db import Session
from app.core.fantasy import race_value
from app.core.map_order import rules_of
from app.core.scoring import DEFAULT_SYSTEM, points_case, wins_of
from app.models.match import Match
from app.models.relationships import DBUserSeasonSignup
from app.models.season import Season
from app.models.series import Series
from app.models.series_cast import SeriesCast, channel_name, is_video_url
from app.models.series_summary import (
    SeriesCastSummaryPublic,
    SeriesPlayerPublic,
    SeriesSummaryPublic,
)
from app.models.user import User
from app.services import derived


def _casts(
    session: OrmSession, scored: dict[int, bool]
) -> dict[int, list[SeriesCastSummaryPublic]]:
    """Every cast of the named series by id, named as CastPublic.from_cast names it."""
    if not scored:
        return {}
    rows = session.execute(
        select(
            col(SeriesCast.id),
            col(SeriesCast.series_id),
            col(SeriesCast.channel_url),
            col(SeriesCast.vod_url),
            col(User.name),
        )
        .join(User, col(User.id) == SeriesCast.user_id, isouter=True)
        .where(col(SeriesCast.series_id).in_(scored))
        .order_by(col(SeriesCast.id))
    ).all()
    found: dict[int, list[SeriesCastSummaryPublic]] = {}
    for cast_id, series_id, channel, vod, name in rows:
        # A video URL claimed as the channel is its own VOD once the series is over
        video = channel if scored[series_id] and is_video_url(channel) else None
        found.setdefault(series_id, []).append(
            SeriesCastSummaryPublic(
                id=cast_id,
                name=name or channel_name(channel),
                channel_url=channel,
                vod_url=vod or video,
            )
        )
    return found


def _player(row: Row[Any], side: int) -> SeriesPlayerPublic | None:
    player_id = getattr(row, f"player{side}_id")
    if player_id is None:
        return None
    return SeriesPlayerPublic(
        id=player_id,
        name=getattr(row, f"player{side}_name"),
        race=race_value(getattr(row, f"player{side}_race")),
    )


def for_event(
    event_id: int,
    limit: int = 500,
    offset: int = 0,
    *,
    player_id: int | None = None,
    team_id: int | None = None,
    match_id: int | None = None,
    is_fantasy_match: bool | None = None,
) -> list[SeriesSummaryPublic]:
    """One page of the event's fixture series in id order, optionally filtered.

    The filters are those of the detail list and AND together.
    """
    player1, player2 = aliased(User), aliased(User)
    signup1, signup2 = aliased(DBUserSeasonSignup), aliased(DBUserSeasonSignup)
    conds: list[ColumnElement[bool]] = [
        col(Match.season_id) == event_id,
        col(Series.entrant1_id).is_(None),
        col(Series.entrant2_id).is_(None),
    ]
    if player_id is not None:
        conds.append(
            or_(
                col(Series.player1_id) == player_id, col(Series.player2_id) == player_id
            )
        )
    if team_id is not None:
        conds.append(
            or_(col(Match.team1_id) == team_id, col(Match.team2_id) == team_id)
        )
    if match_id is not None:
        conds.append(col(Series.match_id) == match_id)
    if is_fantasy_match is not None:
        # A null flag counts as not fantasy
        flag = func.coalesce(col(Series.is_fantasy_match), False)
        conds.append(flag == is_fantasy_match)

    with Session.begin() as session:
        season = session.execute(
            select(col(Season.score_system), col(Season.map_rules)).where(
                col(Season.id) == event_id
            )
        ).first()
        if season is None:
            return []
        system = season.score_system or DEFAULT_SYSTEM
        wins = wins_of(len(rules_of(season.map_rules)))
        one, two = col(Series.player1_score), col(Series.player2_score)
        found = session.execute(
            select(
                col(Series.id),
                col(Match.season_id),
                col(Series.match_id),
                col(Match.playday).label("week"),
                col(Series.date_time),
                col(Series.player1_id),
                col(player1.name).label("player1_name"),
                derived.race_of(col(Series.player1_off_race), signup1).label(
                    "player1_race"
                ),
                col(Series.player2_id),
                col(player2.name).label("player2_name"),
                derived.race_of(col(Series.player2_off_race), signup2).label(
                    "player2_race"
                ),
                one.label("player1_score"),
                two.label("player2_score"),
                points_case(one, two, system, wins).label("player1_points"),
                points_case(two, one, system, wins).label("player2_points"),
            )
            .join(Match, col(Match.id) == Series.match_id)
            .join(player1, col(player1.id) == Series.player1_id, isouter=True)
            .join(player2, col(player2.id) == Series.player2_id, isouter=True)
            .join(
                signup1,
                derived.signup_on(signup1, col(Series.player1_id)),
                isouter=True,
            )
            .join(
                signup2,
                derived.signup_on(signup2, col(Series.player2_id)),
                isouter=True,
            )
            .where(*conds)
            .order_by(col(Series.id))
            .limit(limit)
            .offset(offset)
        ).all()
        casts = _casts(
            session,
            {
                row.id: row.player1_score is not None or row.player2_score is not None
                for row in found
            },
        )
    return [
        SeriesSummaryPublic(
            id=row.id,
            season_id=row.season_id,
            match_id=row.match_id,
            week=row.week,
            date_time=row.date_time,
            player1=_player(row, 1),
            player2=_player(row, 2),
            player1_score=row.player1_score,
            player2_score=row.player2_score,
            player1_points=row.player1_points,
            player2_points=row.player2_points,
            casts=casts.get(row.id, []),
        )
        for row in found
    ]
