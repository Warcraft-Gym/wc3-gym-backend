"""What a cup holds beside the event row: its own settings and its entrants' pins.

A cup's choices that no other kind of event reads live here, keyed by the
event or the entrant, so the shared `event` and `event_entrant` rows carry no
cup-only column and no GNL or KOTH read changes. `uses_divisions` is the
cup's choice at creation: off, the cup plays one field and shows no division
anywhere. The two pins split what `manual_placement` means on a KOTH night:
a player placed in a division by hand, and a player whose seed a reshuffle
keeps.
"""

from sqlalchemy import false
from sqlmodel import Field, SQLModel

from app.models.base import DBModel


class CupSettings(DBModel, table=True):
    __tablename__ = "cup_settings"

    event_id: int = Field(primary_key=True, foreign_key="event.id", ondelete="CASCADE")
    # On: the cup splits its players into divisions, cut on its run page
    uses_divisions: bool = Field(
        default=False, sa_column_kwargs={"server_default": false()}
    )


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


class CupPinWrite(SQLModel):
    """The pins a runner sets on one cup entrant; a pin the body leaves out stays."""

    division_pinned: bool | None = None
    seed_pinned: bool | None = None
