"""One division of an event: a band of entrants that plays its own table.

An admin sets the lower bound of each band and assigns entrants from the MMR
the draft page shows, or by hand.
"""

from typing import Annotated

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from app.models.base import DBModel
from app.models.types import NumToStr


class EventDivision(DBModel, table=True):
    __tablename__ = "event_division"
    __table_args__ = (UniqueConstraint("event_id", "position"),)

    id: int | None = Field(default=None, primary_key=True)
    event_id: int = Field(index=True, foreign_key="event.id", ondelete="CASCADE")
    # Divisions read in this order, the strongest first
    position: int = Field(default=1)
    name: Annotated[str | None, NumToStr] = Field(default=None, max_length=50)
    # The MMR the division opens at; null while the bands are unset
    lower_bound: int | None = None
    # How many entrants the division takes when the cut counts from the top
    size: int | None = None


class EventDivisionPublic(SQLModel):
    """One division as the event page reads it."""

    id: int
    position: int
    name: Annotated[str | None, NumToStr] = None
    lower_bound: int | None = None
    size: int | None = None
    # The entrants of this division who have not withdrawn
    entrant_count: int | None = None


class EventDivisionWrite(SQLModel):
    """One division as an admin writes it; its place in the list is its position."""

    name: Annotated[str | None, NumToStr] = None
    lower_bound: int | None = None
    size: int | None = None
