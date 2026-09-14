"""What an event hands out when it closes: one row per place it awards.

The row names the entrant that took the place and the player or the team
behind it, so a trophy read lists a cup win beside a season championship
without knowing which kind of event paid it.
"""

from datetime import datetime
from typing import Annotated

from sqlmodel import Field, SQLModel

from app.models.base import DBModel
from app.models.types import AwareUTC, UTCDateTime, utcnow


class EventAward(DBModel, table=True):
    __tablename__ = "event_award"

    id: int | None = Field(default=None, primary_key=True)
    event_id: int = Field(index=True, foreign_key="event.id", ondelete="CASCADE")
    entrant_id: int | None = Field(
        default=None, foreign_key="event_entrant.id", ondelete="SET NULL"
    )
    user_id: int | None = Field(
        default=None, foreign_key="users.id", ondelete="CASCADE"
    )
    team_id: int | None = Field(
        default=None, foreign_key="teams.id", ondelete="CASCADE"
    )
    # The place the award pays; null for a title that ranks nobody
    place: int | None = None
    title: str = Field(max_length=50)
    awarded_at: Annotated[datetime, AwareUTC] = Field(
        default_factory=utcnow, sa_type=UTCDateTime
    )


class EventAwardPublic(SQLModel):
    """One award as the event page and a player profile read it."""

    id: int
    event_id: int
    entrant_id: int | None = None
    user_id: int | None = None
    team_id: int | None = None
    place: int | None = None
    title: str
    awarded_at: Annotated[datetime, AwareUTC]
