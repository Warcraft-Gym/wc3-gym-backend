"""One side of a series that is not a plain 1v1: a lobby seat or a team side.

An FFA lobby is one series holding one row per player, each with its place.
A 2v2 or a 4v4 side is the rows that share a `side_no`, and `place` repeats on
every row of that side on purpose, so a box reads one table and joins nothing.
A 1v1 series writes no row here, so every GNL read keeps its shape.
"""

from sqlmodel import Field, SQLModel

from app.models.base import DBModel
from app.models.user import UserPublic


class SeriesSide(DBModel, table=True):
    __tablename__ = "series_side"

    series_id: int = Field(
        primary_key=True, foreign_key="series.id", ondelete="CASCADE"
    )
    # Which side of the series the row plays; an FFA lobby seats one per side
    side_no: int = Field(primary_key=True)
    # A key column takes no null, so 0 says the row names no player yet and the
    # column carries no foreign key; the index is what a player read runs on
    user_id: int = Field(
        default=0,
        primary_key=True,
        index=True,
        sa_column_kwargs={"server_default": "0"},
    )
    entrant_id: int | None = Field(
        default=None, foreign_key="event_entrant.id", ondelete="SET NULL"
    )
    # Where the side finished the series; every row of one side carries it
    place: int | None = None


class SeriesSidePublic(SQLModel):
    """One side of a series as a lobby box and a fixture page read it."""

    side_no: int
    user_id: int | None = None
    # The player in the seat, so a lobby box prints his name and his race
    user: UserPublic | None = None
    entrant_id: int | None = None
    place: int | None = None


class PlaceWrite(SQLModel):
    """Where one side of a lobby finished."""

    side_no: int
    place: int = Field(ge=1)


class PlacesWrite(SQLModel):
    """What an organiser enters for a lobby: the place of every side of it."""

    places: list[PlaceWrite] = []


class LobbySidesWrite(SQLModel):
    """Who sits in a lobby, in seat order; an organiser writes it before the
    round starts, so an entrant may move from one lobby to another."""

    entrant_ids: list[int] = []
