"""When a player says they cannot play: the user_block and user_busy tables.

Both are soft hints for the scheduling tools. They belong to the player, not
to an event, so they carry over, and they never write the per-round answer in
user_season_availability. Times are local to users.timezone and resolve to
instants only against a real date, in app.core.free_time.
"""

from datetime import date, datetime, time

from sqlalchemy import CheckConstraint, Index, SmallInteger, func
from sqlmodel import Field, SQLModel

from app.models.base import DBModel
from app.models.types import UTCDateTime, utcnow


def _created() -> datetime:
    return Field(
        default_factory=utcnow,
        sa_type=UTCDateTime,
        sa_column_kwargs={"server_default": func.now()},
    )


def _updated() -> datetime:
    return Field(
        default_factory=utcnow,
        sa_type=UTCDateTime,
        sa_column_kwargs={"server_default": func.now(), "onupdate": utcnow},
    )


class UserBlockBase(SQLModel):
    label: str | None = Field(default=None, max_length=40)
    # ISO weekday bits: Monday = 1, Tuesday = 2, ... Sunday = 64
    weekdays: int = Field(ge=1, le=127, sa_type=SmallInteger)
    # An end before the start runs past midnight into the next day
    start_local: time
    end_local: time


class UserBlock(UserBlockBase, DBModel, table=True):
    __tablename__ = "user_block"
    __table_args__ = (
        CheckConstraint("weekdays BETWEEN 1 AND 127", name="weekdays"),
        CheckConstraint("end_local <> start_local", name="not_empty"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="users.id", ondelete="CASCADE")
    created_at: datetime = _created()
    updated_at: datetime = _updated()


class UserBlockCreate(UserBlockBase):
    pass


class UserBlockUpdate(SQLModel):
    label: str | None = Field(default=None, max_length=40)
    weekdays: int | None = Field(default=None, ge=1, le=127)
    start_local: time | None = None
    end_local: time | None = None


class UserBlockPublic(UserBlockBase):
    id: int


class UserBusyBase(SQLModel):
    label: str | None = Field(default=None, max_length=40)
    # Whole local days, both ends included
    first_day: date
    last_day: date


class UserBusy(UserBusyBase, DBModel, table=True):
    __tablename__ = "user_busy"
    __table_args__ = (
        CheckConstraint("last_day >= first_day", name="day_order"),
        Index("ix_user_busy_user_id_last_day", "user_id", "last_day"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", ondelete="CASCADE")
    created_at: datetime = _created()
    updated_at: datetime = _updated()


class UserBusyCreate(UserBusyBase):
    pass


class UserBusyUpdate(SQLModel):
    label: str | None = Field(default=None, max_length=40)
    first_day: date | None = None
    last_day: date | None = None


class UserBusyPublic(UserBusyBase):
    id: int


class SoftBlocksPublic(SQLModel):
    """One player's blocks: shown to that player and to admins, never to anyone else."""

    repeating: list[UserBlockPublic]
    busy: list[UserBusyPublic]


class FreeRange(SQLModel):
    start: datetime
    end: datetime


class FreeTimePublic(SQLModel):
    """The hours both players of a series have free in a window, in UTC.

    It carries no block and no player, so it never shows whose block is whose.
    """

    start: datetime
    end: datetime
    hours: float
    ranges: list[FreeRange]
