"""A cup that repeats on a rule: the rule, and the cups made from it.

A recurring cup is a rule, such as every Friday or the first Friday of the
month at a local start time, and its occurrences. Each occurrence is a cup of
its own, made by a runner on one of the rule's dates as a copy of the latest
occurrence, so it keeps its own players, draw and awards. Every row here is a
cup's, so no GNL or KOTH read sees one. The rows are not called a series,
because a cup's series are its games.
"""

from datetime import date, datetime
from typing import Annotated

from pydantic import field_validator
from sqlalchemy import UniqueConstraint, func
from sqlmodel import Field, SQLModel

from app.models.base import DBModel
from app.models.types import AwareUTC, KnownTimeZone, UTCDateTime, utcnow

# The nth weekday of the month a rule names: 1 to 4, or -1 for the last
NTH = (1, 2, 3, 4, -1)
CLOCK = r"^([01]\d|2[0-3]):[0-5]\d$"


class CupRecurrence(DBModel, table=True):
    __tablename__ = "cup_recurrence"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=80)
    # 0 is Monday, 6 is Sunday
    weekday: int
    # Null plays every week; 1 to 4 the nth such weekday of the month; -1 the last
    nth: int | None = None
    # The local start time, "HH:MM", in `zone`
    start_time: str = Field(max_length=5)
    zone: str = Field(max_length=64)
    # The first occurrence's day; the rule names no day before it
    starts_on: date
    ends_on: date | None = None
    # The Discord id of the runner who set the rule up
    created_by: str = Field(max_length=50)
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_type=UTCDateTime,
        sa_column_kwargs={"server_default": func.now()},
    )


class CupOccurrence(DBModel, table=True):
    """One cup made from a rule, on one of its days."""

    __tablename__ = "cup_occurrence"
    __table_args__ = (UniqueConstraint("recurrence_id", "occurs_on"),)

    event_id: int = Field(primary_key=True, foreign_key="event.id", ondelete="CASCADE")
    recurrence_id: int = Field(
        index=True, foreign_key="cup_recurrence.id", ondelete="CASCADE"
    )
    occurs_on: date


class CupRecurrenceWrite(SQLModel):
    """A new rule: on which weekday, which of the month, when, and until when."""

    name: str = Field(min_length=1, max_length=80)
    weekday: int = Field(ge=0, le=6)
    nth: int | None = None
    start_time: str = Field(regex=CLOCK)
    zone: Annotated[str, KnownTimeZone] = Field(max_length=64)
    ends_on: date | None = None

    @field_validator("nth")
    @classmethod
    def _known_nth(cls, value: int | None) -> int | None:
        if value is not None and value not in NTH:
            raise ValueError("nth is 1 to 4, -1 for the last, or null for every week")
        return value


class CupRecurrenceUpdate(SQLModel):
    """A rule's change; a field left out keeps its value."""

    name: str | None = Field(default=None, min_length=1, max_length=80)
    start_time: str | None = Field(default=None, regex=CLOCK)
    ends_on: date | None = None


class CupOccurrenceCreate(SQLModel):
    """The day a runner makes the next cup on; one the rule names."""

    on: date


class CupRecurrenceRef(SQLModel):
    """The rule an event was made from, as its page names it."""

    id: int
    name: str


class CupOccurrencePublic(SQLModel):
    """One cup of the rule, as the rule's page lists it."""

    event_id: int
    name: str
    occurs_on: date
    starts_at: Annotated[datetime | None, AwareUTC] = None
    published: bool = True
    closed_at: Annotated[datetime | None, AwareUTC] = None
    cancelled_at: Annotated[datetime | None, AwareUTC] = None


class CupRecurrenceDate(SQLModel):
    """One coming day of the rule, and the cup on it once one is made."""

    on: date
    event_id: int | None = None


class CupRecurrencePublic(SQLModel):
    id: int
    name: str
    weekday: int
    nth: int | None = None
    start_time: str
    zone: str
    starts_on: date
    ends_on: date | None = None
    # The cup the next one is copied from
    latest_event_id: int | None = None
    occurrences: list[CupOccurrencePublic] = []
    # The rule's next days from today, eight of them, or fewer before its end
    upcoming: list[CupRecurrenceDate] = []


class CupRecurrenceRow(SQLModel):
    """One rule of the list: what it plays, its next day and its latest cup."""

    id: int
    name: str
    weekday: int
    nth: int | None = None
    start_time: str
    zone: str
    ends_on: date | None = None
    next_on: date | None = None
    latest_event_id: int | None = None
    occurrence_count: int = 0
