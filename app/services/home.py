"""The home hub read: the next booked series and the casted series of the
whole site, across every event kind.

Three short lists answer one request. Each list costs one statement plus the
two collection loads of a reduced series; the round and the stage of every row
come in one more, and one pass names the race of both sides and rates it. None
of them grows with the number of rows.
"""

from datetime import timedelta
from typing import Any, NamedTuple

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import col

from app.core.db import Session
from app.models.base import ident
from app.models.event_stage import EventStage
from app.models.home import HomeSeries, HomeSeriesRow
from app.models.league import League
from app.models.match import Match
from app.models.relationships import DBEventRound
from app.models.season import Season
from app.models.series import Series, SeriesPublic
from app.models.series_cast import SeriesCast
from app.models.types import utcnow
from app.services import derived

# How long each list is; the hub draws no more than this
NEXT = 5
CASTS_UPCOMING = 3
CASTS_RECENT = 4

# How long a started series with no result stays in the booked lists
GRACE = timedelta(hours=2)


class _Labelled(NamedTuple):
    """One series with the event parts its context label is written from."""

    series: Series
    league: str | None
    event: str | None
    playday: int | None
    event_id: int


class _Round(NamedTuple):
    """What a series' round is called and which stage it sits in."""

    name: str | None
    number: int | None
    stage: str | None


def _unplayed() -> ColumnElement[bool]:
    """A series with neither map score written."""
    return and_(
        col(Series.player1_score).is_(None), col(Series.player2_score).is_(None)
    )


def _played() -> ColumnElement[bool]:
    """A series that carries a result."""
    return or_(
        col(Series.player1_score).is_not(None), col(Series.player2_score).is_not(None)
    )


def _published() -> Select[Any]:
    """Every series of a published event, with the event parts of its label.

    A fixture names its event; a series the stage engine generated names it
    through the round it plays in. The event joins under an alias and the round
    answers as a subquery, because a statement that loads a Season may not also
    join `event_round`: the round count of a season is itself a subquery over
    that table.
    """
    event = aliased(Season, name="home_event")
    round_event = (
        select(col(DBEventRound.season_id))
        .where(col(DBEventRound.id) == col(Series.round_id))
        .scalar_subquery()
    )
    return (
        select(
            Series,
            col(League.short_name),
            col(event.name),
            col(Match.playday),
            col(event.id),
        )
        .outerjoin(Match, col(Match.id) == col(Series.match_id))
        .join(event, col(event.id) == func.coalesce(col(Match.season_id), round_event))
        .outerjoin(League, col(League.id) == col(event.league_id))
        .where(col(event.published).is_(True))
        .options(*Series._list_eager_options())
    )


def _claimed() -> Select[Any]:
    """The series a caster claimed. It stands alone: auto-correlation would
    otherwise leave the subquery without a table of its own."""
    return select(col(SeriesCast.series_id)).select_from(SeriesCast).correlate(None)


def _rows(session: OrmSession, stmt: Select[Any]) -> list[_Labelled]:
    return [_Labelled(*row) for row in session.execute(stmt).unique().all()]


def _rounds(session: OrmSession, series_ids: set[int]) -> dict[int, _Round]:
    """The round and the stage of every named series, in one statement."""
    if not series_ids:
        return {}
    rows = session.execute(
        select(
            col(Series.id),
            col(DBEventRound.name),
            col(DBEventRound.number),
            col(EventStage.name),
        )
        .join(DBEventRound, col(DBEventRound.id) == col(Series.round_id))
        .outerjoin(EventStage, col(EventStage.id) == col(DBEventRound.stage_id))
        .where(col(Series.id).in_(series_ids))
    ).all()
    return {row[0]: _Round(*row[1:]) for row in rows}


def _round_label(row: _Labelled, found: _Round | None) -> str | None:
    """What the label calls the round: its name, else its number, else the playday."""
    if found and found.name:
        return found.name
    number = found.number if found and found.number is not None else row.playday
    return f"Round {number}" if number is not None else None


def series() -> HomeSeries:
    """The three lists the hub draws: what is booked next, and what is cast."""
    now = utcnow()
    with Session() as session:
        # A series that has started but carries no result is still what is on now
        booked = _published().where(col(Series.date_time) >= now - GRACE, _unplayed())
        lists = [
            _rows(
                session,
                booked.order_by(col(Series.date_time), col(Series.id)).limit(NEXT),
            ),
            _rows(
                session,
                booked.where(col(Series.id).in_(_claimed()))
                .order_by(col(Series.date_time), col(Series.id))
                .limit(CASTS_UPCOMING),
            ),
            _rows(
                session,
                _published()
                .where(
                    col(Series.date_time).is_not(None),
                    _played(),
                    col(Series.id).in_(
                        _claimed().where(col(SeriesCast.vod_url).is_not(None))
                    ),
                )
                .order_by(col(Series.date_time).desc(), col(Series.id).desc())
                .limit(CASTS_RECENT),
            ),
        ]
        # A series may sit in two lists, so the pass below names and rates it once
        seen = {ident(row.series): row for rows in lists for row in rows}
        public = {
            key: SeriesPublic.from_series_reduced(row.series)
            for key, row in seen.items()
        }
        derived.fill_signup_races(
            session,
            list(public.values()),
            {key: row.event_id for key, row in seen.items()},
        )
        derived.fill_mmrs(session, list(public.values()))
        rounds = _rounds(session, set(seen))
        made = {
            key: HomeSeriesRow.from_series(
                public[key],
                league=row.league,
                event=row.event,
                stage=rounds[key].stage if key in rounds else None,
                round_name=_round_label(row, rounds.get(key)),
            )
            for key, row in seen.items()
        }
        return HomeSeries(
            next=[made[ident(row.series)] for row in lists[0]],
            casts_upcoming=[made[ident(row.series)] for row in lists[1]],
            casts_recent=[made[ident(row.series)] for row in lists[2]],
        )
