"""One player signed up to an event.

Eligibility warns and never blocks (NE-8), so nothing here refuses a signup:
a withdrawn or unchecked-in entrant keeps its row and its stamps say so.
"""

from datetime import datetime
from typing import Annotated

from sqlalchemy import UniqueConstraint, func
from sqlmodel import Field

from app.models.base import DBModel
from app.models.enums import Race, SignupChannel
from app.models.types import AwareUTC, SuggestRace, UTCDateTime, utcnow


class EventEntrant(DBModel, table=True):
    __tablename__ = "event_entrant"
    __table_args__ = (UniqueConstraint("event_id", "user_id"),)

    id: int | None = Field(default=None, primary_key=True)
    event_id: int = Field(index=True, foreign_key="event.id", ondelete="CASCADE")
    user_id: int = Field(index=True, foreign_key="users.id", ondelete="CASCADE")
    race: Annotated[Race, SuggestRace]
    # Where the stage seeds this entrant; null until the seeds are set
    seed: int | None = None
    division_id: int | None = Field(
        default=None, foreign_key="event_division.id", ondelete="SET NULL"
    )
    channel: SignupChannel = Field(
        default=SignupChannel.web, sa_column_kwargs={"server_default": "web"}
    )
    checked_in_at: Annotated[datetime | None, AwareUTC] = Field(
        default=None, sa_type=UTCDateTime
    )
    withdrawn_at: Annotated[datetime | None, AwareUTC] = Field(
        default=None, sa_type=UTCDateTime
    )
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_type=UTCDateTime,
        sa_column_kwargs={"server_default": func.now()},
    )
