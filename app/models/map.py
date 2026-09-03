from typing import TYPE_CHECKING, Annotated

from sqlalchemy import Index, text
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import DBModel
from app.models.types import NumToStr

if TYPE_CHECKING:
    from app.models.relationships import DBMapSeason


class MapBase(SQLModel):
    # The xlsx import passes cells through, so a numeric name arrives as a number
    name: Annotated[str | None, NumToStr] = Field(default=None, max_length=50)
    shortname: Annotated[str | None, NumToStr] = Field(default=None, max_length=50)
    # where the picture is published: the blob an admin uploaded, else what the ladder import found
    image: Annotated[str | None, NumToStr] = Field(default=None, max_length=500)


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
    pass


class MapUpdate(MapBase):
    pass


class MapPublic(MapBase):
    id: int


class LadderMapRow(SQLModel):
    """One map of the w3champions ladder, as the import preview lists it.

    status is `in_pool` when the season already plays it, `known` when the
    app holds it under this name or an older one of the same lineage,
    `no_match` when warcraft3.info knows no map of that name and version,
    else `new`.
    """

    w3c_name: str
    matched_name: str | None = None
    shortname: str | None = None
    image_url: str | None = None
    status: str = "new"


class LadderMapNames(SQLModel):
    names: list[str]
