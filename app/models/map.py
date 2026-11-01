from typing import TYPE_CHECKING, Annotated

from sqlalchemy import Index, text
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import DBModel
from app.models.types import MapModes, NumToStr

if TYPE_CHECKING:
    from app.models.relationships import DBMapSeason


# The longest name the maps table holds
MAP_NAME_LENGTH = 50


class MapBase(SQLModel):
    name: str | None = Field(default=None, max_length=MAP_NAME_LENGTH)
    shortname: str | None = Field(default=None, max_length=50)
    # where the picture is published: our blob, else the url a map source publishes it at
    image: str | None = Field(default=None, max_length=500)
    # The modes the map is played as, as "1v1,2v2"; null names none yet
    modes: str | None = Field(default=None, max_length=100)


class Map(MapBase, DBModel, table=True):
    __tablename__ = "maps"
    # The import matches a map by short name
    __table_args__ = (
        Index("uq_maps_shortname", text("lower(trim(shortname))"), unique=True),
    )

    id: int | None = Field(default=None, primary_key=True)
    seasons: list["DBMapSeason"] = Relationship(
        back_populates="map", sa_relationship_kwargs={"cascade": "all, delete"}
    )


class MapCreate(MapBase):
    # The xlsx import passes cells through, so a numeric name arrives as a number
    name: Annotated[str | None, NumToStr] = Field(default=None, max_length=50)
    shortname: Annotated[str | None, NumToStr] = Field(default=None, max_length=50)
    image: Annotated[str | None, NumToStr] = Field(default=None, max_length=500)
    modes: Annotated[str | None, MapModes] = Field(default=None, max_length=100)


class MapUpdate(MapBase):
    # The xlsx import passes cells through, so a numeric name arrives as a number
    name: Annotated[str | None, NumToStr] = Field(default=None, max_length=50)
    shortname: Annotated[str | None, NumToStr] = Field(default=None, max_length=50)
    image: Annotated[str | None, NumToStr] = Field(default=None, max_length=500)
    modes: Annotated[str | None, MapModes] = Field(default=None, max_length=100)


class CustomMapCreate(SQLModel):
    """A custom game's map an organizer names: the app finds it, or adds it."""

    name: str = Field(min_length=1, max_length=50)


class MapPublic(MapBase):
    id: int


class LadderMapRow(SQLModel):
    """One map of the w3champions ladder, as the import preview lists it.

    status is `in_pool` when the season already plays it, `known` when the
    app holds it under this name or an older one of the same lineage,
    `no_match` when no map source knows it, else `new`. A map the app holds off
    the ladder lists as `off_ladder` when a source has its picture; importing it
    fills the picture only.
    """

    w3c_name: str
    matched_name: str | None = None
    shortname: str | None = None
    image_url: str | None = None
    status: str = "new"
    # The map of the app a known ladder map is, so a cup's pool can take it as it stands
    map_id: int | None = None
    # The source that knew this map, and every source that could not be read
    source: str | None = None
    unreached: list[str] = Field(default_factory=list)


class LadderMapNames(SQLModel):
    names: list[str]


class MapSourcePublic(SQLModel):
    """A site an admin can take maps from, with what its rows must credit."""

    key: str
    title: str
    credit_url: str
    license: str | None = None


class SourceMapRow(SQLModel):
    """One map of a source. `modes` is the source's suggestion, and `map_id` the
    map of the app it is, which `pictured` says has a picture."""

    name: str
    players: int | None = None
    modes: str | None = None
    shortname: str | None = None
    picture_url: str | None = None
    map_id: int | None = None
    pictured: bool = False


class SourceMapPick(SQLModel):
    """A map an admin picked from a source, and what it is played as."""

    name: str = Field(min_length=1, max_length=MAP_NAME_LENGTH)
    modes: Annotated[str | None, MapModes] = None


class SourceMapPicks(SQLModel):
    # A call copies each map's picture, so it stays inside the function's time limit
    maps: list[SourceMapPick] = Field(min_length=1, max_length=10)
