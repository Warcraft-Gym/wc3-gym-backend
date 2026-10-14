"""A cup that repeats on a rule, and the cups made from it.

A runner of a cup sets up a rule from it: a weekday, every week or the nth of
the month, a local start time and an optional last day. The cup becomes the
rule's first occurrence. The rule's page lists its cups and its next days;
"Create" on a day copies the latest occurrence onto that day as a cup of its
own: its format and stages, its rounds shifted by the same days, its map pool,
its sign-up rules, its divisions choice, its points table and its organizers.
No job makes a cup by itself.
"""

import calendar
from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core.db import Session
from app.core.exceptions import ApiError, BadRequestError, NotFoundError
from app.models.base import ident
from app.models.cup_recurrence import (
    CupOccurrence,
    CupOccurrencePublic,
    CupRecurrence,
    CupRecurrenceDate,
    CupRecurrencePublic,
    CupRecurrenceRef,
    CupRecurrenceRow,
    CupRecurrenceUpdate,
    CupRecurrenceWrite,
)
from app.models.cup_rounds import CupLegWrite
from app.models.cup_settings import CupSettings
from app.models.enums import EventKind
from app.models.event_stage import EventStage, EventStageWrite
from app.models.organizer import EventOrganizer
from app.models.relationships import DBMapSeason
from app.models.season import EventCreate, EventPublic, Season
from app.services import cup_rounds, organizers

# How many of the rule's coming days its page offers
UPCOMING = 8
# The event fields a new occurrence takes from its own day, never from the copy
OWN_FIELDS = {
    "name",
    "start_date",
    "end_date",
    "starts_at",
    "stages",
    "map_ids",
    "legs",
    "points_by_place",
    "uses_divisions",
    "round_count",
    "parent_id",
    "signups_open",
    "recurrence",
}


def nth_weekday(year: int, month: int, weekday: int, nth: int) -> date | None:
    """The nth such weekday of the month, -1 the last; null when the month has
    no fifth one."""
    days = [
        day
        for day in calendar.Calendar().itermonthdates(year, month)
        if day.month == month and day.weekday() == weekday
    ]
    if nth == -1:
        return days[-1]
    return days[nth - 1] if nth <= len(days) else None


def days_of(rule: CupRecurrence, start: date) -> Iterator[date]:
    """The rule's days from `start` on, in order, up to its last day."""
    if rule.nth is None:
        day = start + timedelta(days=(rule.weekday - start.weekday()) % 7)
        while rule.ends_on is None or day <= rule.ends_on:
            yield day
            day += timedelta(days=7)
        return
    year, month = start.year, start.month
    while True:
        day = nth_weekday(year, month, rule.weekday, rule.nth)
        if day is not None and day >= start:
            if rule.ends_on is not None and day > rule.ends_on:
                return
            yield day
        month += 1
        if month > 12:
            year, month = year + 1, 1


def names_day(rule: CupRecurrence, day: date) -> bool:
    """Whether the rule plays on that day."""
    if day.weekday() != rule.weekday or day < rule.starts_on:
        return False
    if rule.ends_on is not None and day > rule.ends_on:
        return False
    return (
        rule.nth is None
        or nth_weekday(day.year, day.month, day.weekday(), rule.nth) == day
    )


def start_of(rule: CupRecurrence, day: date) -> datetime:
    """The UTC instant the rule's start time names on that day, in its zone."""
    hours, minutes = (int(part) for part in rule.start_time.split(":"))
    local = datetime.combine(day, time(hours, minutes), tzinfo=ZoneInfo(rule.zone))
    return local.astimezone(UTC)


def create(
    event_id: int, data: CupRecurrenceWrite, claims: dict[str, Any]
) -> CupRecurrencePublic:
    """Set up a rule from a cup, which becomes its first occurrence."""
    with Session.begin() as session:
        rule = create_in(session, _cup(session, event_id), data, str(claims["sub"]))
        return _public(session, rule)


def create_in(
    session: OrmSession, event: Season, data: CupRecurrenceWrite, created_by: str
) -> CupRecurrence:
    """`create` inside the caller's transaction, so a cup and its rule are
    written together."""
    event_id = ident(event)
    if session.get(CupOccurrence, event_id) is not None:
        raise ApiError(409, {"error": "This cup repeats already"})
    if event.starts_at is None:
        raise BadRequestError("Give the cup a start first; the rule repeats it")
    starts_on = event.starts_at.astimezone(ZoneInfo(data.zone)).date()
    if data.ends_on is not None and data.ends_on < starts_on:
        raise BadRequestError("The last day comes after the cup's own day")
    rule = CupRecurrence(
        **data.model_dump(), starts_on=starts_on, created_by=created_by
    )
    session.add(rule)
    session.flush()
    session.add(
        CupOccurrence(event_id=event_id, recurrence_id=ident(rule), occurs_on=starts_on)
    )
    session.flush()
    return rule


def get(recurrence_id: int) -> CupRecurrencePublic:
    with Session.begin() as session:
        return _public(session, _rule(session, recurrence_id))


def listing() -> list[CupRecurrenceRow]:
    """Every rule, newest first, with its next day and its latest cup."""
    with Session.begin() as session:
        rules = session.scalars(
            select(CupRecurrence).order_by(col(CupRecurrence.id).desc())
        ).all()
        counts: dict[int, int] = {
            recurrence_id: count
            for recurrence_id, count in session.execute(
                select(col(CupOccurrence.recurrence_id), func.count()).group_by(
                    col(CupOccurrence.recurrence_id)
                )
            )
        }
        return [
            CupRecurrenceRow(
                id=ident(rule),
                name=rule.name,
                weekday=rule.weekday,
                nth=rule.nth,
                start_time=rule.start_time,
                zone=rule.zone,
                ends_on=rule.ends_on,
                next_on=next(days_of(rule, _from(rule)), None),
                latest_event_id=_latest(session, ident(rule)),
                occurrence_count=counts.get(ident(rule), 0),
            )
            for rule in rules
        ]


def update(
    recurrence_id: int, data: CupRecurrenceUpdate, claims: dict[str, Any]
) -> CupRecurrencePublic:
    with Session.begin() as session:
        rule = _rule(session, recurrence_id)
        _hold_runner(session, rule, claims)
        changes = data.model_dump(exclude_unset=True)
        if changes.get("ends_on") is not None and changes["ends_on"] < rule.starts_on:
            raise BadRequestError("The last day comes after the first cup's day")
        rule.sqlmodel_update(changes)
        session.flush()
        return _public(session, rule)


def delete(recurrence_id: int, claims: dict[str, Any]) -> None:
    """Stop the rule; every cup made from it stays as it is."""
    with Session.begin() as session:
        rule = _rule(session, recurrence_id)
        _hold_runner(session, rule, claims)
        session.execute(
            sa_delete(CupOccurrence).where(
                col(CupOccurrence.recurrence_id) == recurrence_id
            )
        )
        session.delete(rule)


def create_occurrence(
    recurrence_id: int, day: date, claims: dict[str, Any]
) -> EventPublic:
    """Make the rule's cup on one of its coming days, a copy of the latest one."""
    from app.services.events import EventService

    with Session.begin() as session:
        rule = _rule(session, recurrence_id)
        template = _hold_runner(session, rule, claims)
        if not names_day(rule, day):
            raise BadRequestError("The rule plays on no such day")
        if day < _today(rule):
            raise BadRequestError("That day has passed")
        taken = session.scalar(
            select(col(CupOccurrence.event_id)).where(
                col(CupOccurrence.recurrence_id) == recurrence_id,
                col(CupOccurrence.occurs_on) == day,
            )
        )
        if taken is not None:
            raise ApiError(409, {"error": "That day has its cup already"})
        body = _copy(session, rule, template, day)
        runners = [
            (row.discord_id, row.name)
            for row in session.scalars(
                select(EventOrganizer).where(
                    col(EventOrganizer.event_id) == ident(template)
                )
            )
        ]
    service = EventService()
    made = service.add(body)
    with Session.begin() as session:
        session.add(
            CupOccurrence(event_id=made.id, recurrence_id=recurrence_id, occurs_on=day)
        )
    for discord_id, name in runners:
        organizers.add_to_event(made.id, discord_id, str(claims["sub"]), name)
    if claims["sub"] != "admin":
        organizers.add_to_event(made.id, str(claims["sub"]), str(claims["sub"]))
    return service.get(made.id, claims=claims)


def ref_of(session: OrmSession, event_id: int) -> CupRecurrenceRef | None:
    """The rule a cup was made from, for its page; null for a cup of its own."""
    row = session.execute(
        select(col(CupRecurrence.id), col(CupRecurrence.name))
        .join(CupOccurrence, col(CupOccurrence.recurrence_id) == col(CupRecurrence.id))
        .where(col(CupOccurrence.event_id) == event_id)
    ).first()
    return CupRecurrenceRef(id=row[0], name=row[1]) if row else None


def _copy(
    session: OrmSession, rule: CupRecurrence, template: Season, day: date
) -> EventCreate:
    """The body POST /events would take for the rule's cup on that day."""
    fields = {
        name: getattr(template, name)
        for name in EventCreate.model_fields
        if name not in OWN_FIELDS and hasattr(template, name)
    }
    starts_at = start_of(rule, day)
    legs = cup_rounds.legs_of(session, ident(template))
    stage_ids = legs[0].stage_ids if legs else None
    stages = session.scalars(
        select(EventStage)
        .where(
            col(EventStage.event_id) == ident(template),
            *([col(EventStage.id).in_(stage_ids)] if stage_ids is not None else []),
        )
        .order_by(col(EventStage.position))
    ).all()
    settings = session.get(CupSettings, ident(template))
    pool = session.scalars(
        select(col(DBMapSeason.map_id))
        .where(col(DBMapSeason.season_id) == ident(template))
        .order_by(col(DBMapSeason.position))
    ).all()
    shift = starts_at - template.starts_at if template.starts_at else timedelta(0)
    return EventCreate(
        **fields,
        name=f"{rule.name} {day.day} {day:%b %Y}",
        start_date=day,
        end_date=None,
        starts_at=starts_at,
        signups_open=True,
        stages=[
            EventStageWrite.model_validate(stage, from_attributes=True)
            for stage in stages
        ],
        map_ids=list(pool),
        uses_divisions=bool(settings and settings.uses_divisions),
        legs=[
            CupLegWrite(
                name=leg.name,
                starts_at=_shifted(leg.starts_at, shift, rule.zone)
                if index
                else starts_at,
            )
            for index, leg in enumerate(legs)
        ],
        points_by_place=cup_rounds.points_of(settings.points_by_place)
        if legs and settings
        else None,
    )


def _shifted(moment: datetime | None, shift: timedelta, zone: str) -> datetime | None:
    """A later round's start moved by the days between the two cups, at the
    same wall-clock time in the rule's zone."""
    if moment is None:
        return None
    local = moment.astimezone(ZoneInfo(zone))
    days = timedelta(days=round(shift.total_seconds() / 86400))
    return datetime.combine(local.date() + days, local.timetz()).astimezone(UTC)


def _public(session: OrmSession, rule: CupRecurrence) -> CupRecurrencePublic:
    rows = session.execute(
        select(CupOccurrence, Season)
        .join(Season, col(Season.id) == col(CupOccurrence.event_id))
        .where(col(CupOccurrence.recurrence_id) == ident(rule))
        .order_by(col(CupOccurrence.occurs_on))
    ).all()
    made = {occurrence.occurs_on: occurrence.event_id for occurrence, _ in rows}
    upcoming = []
    for day in days_of(rule, _from(rule)):
        upcoming.append(CupRecurrenceDate(on=day, event_id=made.get(day)))
        if len(upcoming) == UPCOMING:
            break
    return CupRecurrencePublic(
        **rule.model_dump(exclude={"created_by", "created_at"}),
        latest_event_id=rows[-1][0].event_id if rows else None,
        occurrences=[
            CupOccurrencePublic(
                event_id=occurrence.event_id,
                name=event.name,
                occurs_on=occurrence.occurs_on,
                starts_at=event.starts_at,
                published=event.published,
                closed_at=event.closed_at,
                cancelled_at=event.cancelled_at,
            )
            for occurrence, event in rows
        ],
        upcoming=upcoming,
    )


def _today(rule: CupRecurrence) -> date:
    return datetime.now(ZoneInfo(rule.zone)).date()


def _from(rule: CupRecurrence) -> date:
    """The first day the rule's coming days count from: today, or its first day."""
    return max(_today(rule), rule.starts_on)


def _latest(session: OrmSession, recurrence_id: int) -> int | None:
    return session.scalar(
        select(col(CupOccurrence.event_id))
        .where(col(CupOccurrence.recurrence_id) == recurrence_id)
        .order_by(col(CupOccurrence.occurs_on).desc())
        .limit(1)
    )


def _hold_runner(
    session: OrmSession, rule: CupRecurrence, claims: dict[str, Any]
) -> Season:
    """The latest cup of the rule, which the caller must run: an admin, or one
    of that cup's organizers."""
    latest = _latest(session, ident(rule))
    template = session.get(Season, latest) if latest is not None else None
    if template is None:
        raise NotFoundError("The rule has no cup left to copy")
    if not organizers.runs_in(session, claims, ident(template)):
        raise ApiError(403, {"error": "Only the cup's organizers"})
    return template


def _rule(session: OrmSession, recurrence_id: int) -> CupRecurrence:
    rule = session.get(CupRecurrence, recurrence_id)
    if rule is None:
        raise NotFoundError(f"Recurring cup not found by id: {recurrence_id}")
    return rule


def _cup(session: OrmSession, event_id: int) -> Season:
    event = session.get(Season, event_id)
    if event is None:
        raise NotFoundError(f"Event not found by id: {event_id}")
    if event.kind is not EventKind.cup:
        raise BadRequestError("Only a cup repeats")
    return event
