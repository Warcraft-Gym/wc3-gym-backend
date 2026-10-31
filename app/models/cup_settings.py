"""What a cup holds beside the event row: its own settings, its entrants' pins
and their places in its line.

A cup's choices that no other kind of event reads live here, keyed by the
event or the entrant, so the shared `event` and `event_entrant` rows carry no
cup-only column and no GNL or KOTH read changes. `uses_divisions` is the
cup's choice at creation: off, the cup plays one field and shows no division
anywhere. The two pins split what `manual_placement` means on a KOTH night:
a player placed in a division by hand, and a player whose seed a reshuffle
keeps. The line orders a cup's sign-ups, so the cup knows who is in and who
waits on its waitlist.
"""

from datetime import datetime
from typing import Annotated

from sqlalchemy import false
from sqlmodel import Field, SQLModel

from app.models.base import DBModel
from app.models.types import AwareUTC, UTCDateTime


class CupSettings(DBModel, table=True):
    __tablename__ = "cup_settings"

    event_id: int = Field(primary_key=True, foreign_key="event.id", ondelete="CASCADE")
    # On: the cup splits its players into divisions, cut on its run page
    uses_divisions: bool = Field(
        default=False, sa_column_kwargs={"server_default": false()}
    )
    # On: a custom game cup, played on one map of its pool with no veto, every
    # game of a series on it
    custom_game: bool = Field(
        default=False, sa_column_kwargs={"server_default": false()}
    )
    # A cup played over rounds: the points each place of a round pays, best place
    # first, as "10,8,6,5,4,3,2,1"; a place past the list pays none
    points_by_place: str | None = Field(default=None, max_length=200)


class CupEntrantPin(DBModel, table=True):
    __tablename__ = "cup_entrant_pin"

    entrant_id: int = Field(
        primary_key=True, foreign_key="event_entrant.id", ondelete="CASCADE"
    )
    # On: a runner put the player in its division, so a new cut leaves it there
    division_pinned: bool = Field(
        default=False, sa_column_kwargs={"server_default": false()}
    )
    # On: a reshuffle keeps the player's seed
    seed_pinned: bool = Field(
        default=False, sa_column_kwargs={"server_default": false()}
    )


class CupEntrantLine(DBModel, table=True):
    """A cup entrant's place in the cup's line: the first places are in, the
    rest wait. An entrant with no row stands at its row's creation."""

    __tablename__ = "cup_entrant_line"

    entrant_id: int = Field(
        primary_key=True, foreign_key="event_entrant.id", ondelete="CASCADE"
    )
    # When the entrant last signed up, so one who withdrew and comes back
    # stands at the end of the line
    joined_at: Annotated[datetime, AwareUTC] = Field(sa_type=UTCDateTime)
    # On: a runner let the entrant in by hand, so the line never sends it back
    held_in: bool = Field(default=False, sa_column_kwargs={"server_default": false()})


class CupPinWrite(SQLModel):
    """The pins a runner sets on one cup entrant; a pin the body leaves out stays."""

    division_pinned: bool | None = None
    seed_pinned: bool | None = None
