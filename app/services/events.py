"""The read side of the events module: events with their phase, stages and divisions.

A GNL season is one event of the GNL league, so these reads run over the same
rows the season pages read; the season payloads are unchanged and keep their
own phase word. The event phase here is computed on every read and never
stored (NE-9).
"""

from collections.abc import Sequence
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core.db import Session
from app.core.exceptions import NotFoundError
from app.models.base import ident
from app.models.event_division import EventDivision, EventDivisionPublic
from app.models.event_entrant import EventEntrant
from app.models.event_stage import EventStage, EventStagePublic
from app.models.league import League, LeaguePublic
from app.models.relationships import DBUserSeasonSignup
from app.models.season import (
    EventPhase,
    EventPublic,
    MemberEventRow,
    Season,
    series_counts,
    series_counts_by_event,
)
from app.models.types import utcnow

# The counts of an event whose series are not written yet
_NO_SERIES = (0, 0, 0)


def phase_of(
    session: OrmSession, event: Season, counts: tuple[int, int, int] | None = None
) -> EventPhase:
    """The phase of an event, read off what is stored rather than a status column.

    The rungs run from the last one back: an unpublished event is a draft, an
    event whose series are all scored or whose end date has passed is
    finished, one with a series scored or past its time is running, then the
    check-in window and the signup window. Seeded is the resting rung, so a
    season whose rounds exist still reads as open for signups while they are.
    Pass `counts` to reuse one grouped series count over a page of events.
    """
    if not event.published:
        return "draft"
    total, started, scored = (
        counts if counts is not None else series_counts(session, event.id)
    )
    if (total and total == scored) or (event.end_date and event.end_date < _today()):
        return "finished"
    if started:
        return "running"
    now = utcnow()
    opens, closes = event.checkin_opens_at, event.checkin_closes_at
    if opens and opens <= now and (closes is None or now < closes):
        return "checkin"
    if event.signups_open and (opens is None or now < opens):
        return "signups_open"
    return "seeded"


def _today() -> date:
    return utcnow().date()


class EventService:
    def get_all(self, limit: int | None = None, offset: int = 0) -> list[EventPublic]:
        """One page of published events: this is the member-facing list, so no drafts."""
        with Session.begin() as session:
            # Offset paging is deterministic only with a fixed order
            events = session.scalars(
                select(Season)
                .where(col(Season.published).is_(True))
                .order_by(col(Season.id))
                .offset(offset)
                .limit(limit)
            ).all()
            return _publics(session, events)

    def get(self, event_id: int) -> EventPublic:
        """One event with its stages, its divisions and how many entrants it holds."""
        with Session.begin() as session:
            event = session.get(Season, event_id)
            if event is None:
                raise NotFoundError(f"Event not found by id: {event_id}")
            return _public(session, event, full=True)

    def get_leagues(self) -> list[LeaguePublic]:
        """Every league, without its events."""
        with Session.begin() as session:
            leagues = session.scalars(select(League).order_by(col(League.id))).all()
            return [LeaguePublic.model_validate(league) for league in leagues]

    def get_league(self, league_id: int) -> LeaguePublic:
        """One league and the events that are its runs, newest first.

        The league page is the admin one, so its drafts are listed.
        """
        with Session.begin() as session:
            league = session.get(League, league_id)
            if league is None:
                raise NotFoundError(f"League not found by id: {league_id}")
            events = session.scalars(
                select(Season)
                .where(col(Season.league_id) == league_id)
                .order_by(col(Season.id).desc())
            ).all()
            public = LeaguePublic.model_validate(league)
            public.events = _publics(session, events)
            return public

    def events_for_member(self, user_id: int | None) -> list[MemberEventRow]:
        """The member home's published events, newest first, every kind in one list.

        One function over the event rows replaces the season and KOTH split.
        `joined` is the caller's own; a caller with no id has joined nothing.
        """
        with Session.begin() as session:
            events = session.scalars(
                select(Season)
                .where(col(Season.published).is_(True))
                .order_by(col(Season.id).desc())
            ).all()
            joined = _joined_events(session, user_id)
            counts = series_counts_by_event(session, [event.id for event in events])
            return [
                MemberEventRow(
                    kind=event.kind,
                    id=ident(event),
                    name=event.name,
                    start=event.start_date or _day(event),
                    end=event.end_date,
                    phase=phase_of(
                        session, event, counts.get(ident(event), _NO_SERIES)
                    ),
                    signups_open=event.signups_open,
                    joined=event.id in joined,
                    url=event.page_url,
                )
                for event in events
            ]


def _day(event: Season) -> date | None:
    """The day a cup or a KOTH night starts, for an event that carries no dates."""
    return event.starts_at.date() if event.starts_at else None


def _joined_events(session: OrmSession, user_id: int | None) -> set[int]:
    """The events the player entered: an entrant row, or a GNL season signup."""
    if user_id is None:
        return set()
    entered = session.scalars(
        select(col(EventEntrant.event_id)).where(
            col(EventEntrant.user_id) == user_id,
            col(EventEntrant.withdrawn_at).is_(None),
        )
    )
    signed = session.scalars(
        select(col(DBUserSeasonSignup.season_id)).where(
            col(DBUserSeasonSignup.user_id) == user_id
        )
    )
    return set(entered) | set(signed)


def _publics(session: OrmSession, events: Sequence[Season]) -> list[EventPublic]:
    """A page of event payloads, with one grouped series count behind their phases."""
    counts = series_counts_by_event(session, [event.id for event in events])
    return [
        _public(session, event, counts=counts.get(ident(event), _NO_SERIES))
        for event in events
    ]


def _public(
    session: OrmSession,
    event: Season,
    full: bool = False,
    counts: tuple[int, int, int] | None = None,
) -> EventPublic:
    """One event payload; the stages, divisions and entrant count only when it is
    the subject of the read.
    """
    public = EventPublic.model_validate(event)
    public.phase = phase_of(session, event, counts)
    if not full:
        return public
    public.stages = [
        EventStagePublic.model_validate(row)
        for row in session.scalars(
            select(EventStage)
            .where(col(EventStage.event_id) == event.id)
            .order_by(col(EventStage.position))
        )
    ]
    public.divisions = [
        EventDivisionPublic.model_validate(row)
        for row in session.scalars(
            select(EventDivision)
            .where(col(EventDivision.event_id) == event.id)
            .order_by(col(EventDivision.position))
        )
    ]
    public.entrant_count = session.scalar(
        select(func.count())
        .select_from(EventEntrant)
        .where(
            col(EventEntrant.event_id) == event.id,
            col(EventEntrant.withdrawn_at).is_(None),
        )
    )
    return public
