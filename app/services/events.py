"""The events module reads and writes: leagues, events, their stages and phase.

A GNL season is one event of the GNL league, so these reads run over the same
rows the season pages read; the season payloads are unchanged and keep their
own phase word. The event phase is computed on every read and never stored.
"""

from collections.abc import Sequence
from datetime import date, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core.db import Session
from app.core.exceptions import NotFoundError
from app.models.base import ident
from app.models.enums import EventKind, StageFormat
from app.models.event_division import EventDivision, EventDivisionPublic
from app.models.event_entrant import EventEntrant
from app.models.event_stage import EventStage, EventStagePublic, EventStageWrite
from app.models.league import League, LeagueCreate, LeaguePublic, LeagueUpdate
from app.models.relationships import DBUserSeasonSignup
from app.models.season import (
    NO_SERIES,
    EventCreate,
    EventPhase,
    EventPublic,
    EventUpdate,
    MemberEventRow,
    Season,
    series_counts,
    series_counts_by_event,
)
from app.models.types import utcnow


def phase_of(
    session: OrmSession, event: Season, counts: tuple[int, int, int] | None = None
) -> EventPhase:
    """The phase of an event, read off what is stored rather than a status column.

    The rungs run from the last one back: an unpublished event is a draft, an
    event whose series are all scored or whose end date has passed is
    finished, one with a series started is running, then the signup window and
    the check-in window of the first round. Seeded is the resting rung.
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
    if event.signups_open:
        return "signups_open"
    if event.checkin_enabled and checkin_open(event):
        return "checkin"
    return "seeded"


def checkin_open(event: Season) -> bool:
    """Whether the check-in window of the event's first round stands open.

    The window opens `checkin_days` before the round starts and closes when
    the round ends; a blank `checkin_days` keeps it open. An event with no
    rounds has nothing to check into.
    """
    # The relationship orders the rounds by playday, so the first is the earliest
    first = next(iter(event.rounds), None)
    if first is None:
        return False
    if event.checkin_days is None or first.start_date is None:
        return True
    now = _today()
    return first.start_date - timedelta(days=event.checkin_days) <= now and (
        first.end_date is None or now <= first.end_date
    )


def _today() -> date:
    return utcnow().date()


class EventService:
    def get_all(
        self,
        kind: EventKind | None = None,
        league_id: int | None = None,
        published: bool | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[EventPublic]:
        """One page of events, newest first, each with its computed phase."""
        statement = select(Season).order_by(col(Season.id).desc())
        if kind is not None:
            statement = statement.where(col(Season.kind) == kind)
        if league_id is not None:
            statement = statement.where(col(Season.league_id) == league_id)
        if published is not None:
            statement = statement.where(col(Season.published).is_(published))
        with Session.begin() as session:
            events = session.scalars(statement.offset(offset).limit(limit)).all()
            return _publics(session, events)

    def get(self, event_id: int) -> EventPublic:
        """One event with its stages, its divisions and how many entrants it holds."""
        with Session.begin() as session:
            return _public(session, _event(session, event_id), full=True)

    def add(self, data: EventCreate) -> EventPublic:
        """Create an event and the stages it plays, or one default stage."""
        with Session.begin() as session:
            fields = data.model_dump(exclude={"stages"})
            event = Season(**fields)
            session.add(event)
            session.flush()
            _write_stages(session, event, data.stages)
            return _public(session, event, full=True)

    def update(self, event_id: int, data: EventUpdate) -> EventPublic:
        """Change the event fields the body names; the stages have their own route."""
        with Session.begin() as session:
            event = _event(session, event_id)
            event.sqlmodel_update(data.model_dump(exclude_unset=True))
            session.flush()
            return _public(session, event, full=True)

    def set_stages(
        self, event_id: int, stages: Sequence[EventStageWrite]
    ) -> EventPublic:
        """Replace the event's stage list; the order of the body is the order played."""
        with Session.begin() as session:
            event = _event(session, event_id)
            session.execute(
                delete(EventStage).where(col(EventStage.event_id) == event_id)
            )
            _write_stages(session, event, stages)
            return _public(session, event, full=True)

    def get_leagues(self) -> list[LeaguePublic]:
        """Every league, without its events."""
        with Session.begin() as session:
            leagues = session.scalars(select(League).order_by(col(League.id))).all()
            return [LeaguePublic.model_validate(league) for league in leagues]

    def get_league(self, league_id: int) -> LeaguePublic:
        """One league and the events that are its runs, newest first."""
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

    def add_league(self, data: LeagueCreate) -> LeaguePublic:
        with Session.begin() as session:
            league = League(**data.model_dump())
            session.add(league)
            session.flush()
            return LeaguePublic.model_validate(league)

    def update_league(self, league_id: int, data: LeagueUpdate) -> LeaguePublic:
        with Session.begin() as session:
            league = session.get(League, league_id)
            if league is None:
                raise NotFoundError(f"League not found by id: {league_id}")
            league.sqlmodel_update(data.model_dump(exclude_unset=True))
            session.flush()
            return LeaguePublic.model_validate(league)

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
                    phase=phase_of(session, event, counts.get(event.id, NO_SERIES)),
                    signups_open=event.signups_open,
                    joined=event.id in joined,
                    url=event.page_url,
                )
                for event in events
            ]


def _event(session: OrmSession, event_id: int) -> Season:
    event = session.get(Season, event_id)
    if event is None:
        raise NotFoundError(f"Event not found by id: {event_id}")
    return event


def _write_stages(
    session: OrmSession, event: Season, stages: Sequence[EventStageWrite]
) -> None:
    """Write the stages in the order the body gives them, or one default stage."""
    rows = list(stages) or [_default_stage(event)]
    session.add_all(
        EventStage(event_id=ident(event), position=position, **stage.model_dump())
        for position, stage in enumerate(rows, start=1)
    )
    session.flush()


def _default_stage(event: Season) -> EventStageWrite:
    """The stage an event with no stage list plays: its own maps, round robin."""
    rules = event.map_rules.split(",") if event.map_rules else []
    return EventStageWrite(
        format=StageFormat.round_robin,
        best_of=len(rules) or 3,
        map_rules=event.map_rules,
    )


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
        _public(session, event, counts=counts.get(event.id, NO_SERIES))
        for event in events
    ]


def _public(
    session: OrmSession,
    event: Season,
    full: bool = False,
    counts: tuple[int, int, int] | None = None,
) -> EventPublic:
    """One event payload; the stages, the divisions and the entrant count only
    when it is the subject of the read.
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
