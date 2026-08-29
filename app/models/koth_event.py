from datetime import datetime
from typing import Annotated

from sqlmodel import Field, Relationship, SQLModel

from app.models.base import DBModel
from app.models.koth_match import KothMatch, KothMatchPublic
from app.models.koth_signup import KothSignup, KothSignupPublic
from app.models.types import AwareUTC, NoneToList, UTCDateTime, utcnow


class KothEventBase(SQLModel):
    name: str = Field(max_length=100)
    description: str | None = Field(default=None, max_length=500)
    event_date: Annotated[datetime, AwareUTC] = Field(
        default_factory=utcnow, sa_type=UTCDateTime
    )
    is_active: bool = True
    bracket_1_threshold: int = 1450  # < this value
    bracket_2_threshold: int = 1600  # >= bracket_1 and < this value
    # bracket 3 is >= bracket_2_threshold


class KothEvent(KothEventBase, DBModel, table=True):
    __tablename__ = "koth_events"

    id: int | None = Field(default=None, primary_key=True)

    # Relationships
    signups: list[KothSignup] = Relationship(
        back_populates="event",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    matches: list[KothMatch] = Relationship(
        back_populates="event",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class KothEventCreate(KothEventBase):
    pass


class KothEventUpdate(SQLModel):
    name: str | None = None
    description: str | None = None
    event_date: Annotated[datetime | None, AwareUTC] = None
    is_active: bool | None = None
    bracket_1_threshold: int | None = None
    bracket_2_threshold: int | None = None


class KothEventPublic(KothEventBase):
    id: int
    event_date: datetime | None = None
    signups: Annotated[list[KothSignupPublic], NoneToList] = []
    matches: Annotated[list[KothMatchPublic], NoneToList] = []
