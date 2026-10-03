"""A crown change of a KOTH bracket that no result shows.

The results of a bracket, walked in the order of play, crown its king. A
crown passed or emptied by hand, or by a rule such as a king who leaves or
moves, sits in that walk at its place: after the series whose sequence is
`after_sequence`. A null entrant empties the throne.
"""

from datetime import datetime
from typing import Annotated

from sqlmodel import Field

from app.models.base import DBModel
from app.models.types import AwareUTC, UTCDateTime, utcnow


class KothCrownEvent(DBModel, table=True):
    __tablename__ = "koth_crown_event"

    id: int | None = Field(default=None, primary_key=True)
    division_id: int = Field(
        index=True, foreign_key="event_division.id", ondelete="CASCADE"
    )
    # The highest sequence of a scored series of the bracket then; 0 before any
    after_sequence: int = Field(default=0)
    # The row the crown passed to; null is an empty throne
    entrant_id: int | None = Field(
        default=None, foreign_key="event_entrant.id", ondelete="SET NULL"
    )
    created_at: Annotated[datetime, AwareUTC] = Field(
        default_factory=utcnow, sa_type=UTCDateTime
    )
