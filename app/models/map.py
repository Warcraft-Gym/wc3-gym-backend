from typing import TYPE_CHECKING, Annotated

from sqlalchemy import Column, Index, LargeBinary, text
from sqlalchemy.orm import deferred
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import DBModel
from app.models.types import NumToStr

if TYPE_CHECKING:
    from app.models.relationships import DBMapSeason

icon_column = Column("icon", LargeBinary)


class MapBase(SQLModel):
    # The xlsx import passes cells through, so a numeric name arrives as a number
    name: Annotated[str | None, NumToStr] = Field(default=None, max_length=50)
    shortname: Annotated[str | None, NumToStr] = Field(default=None, max_length=50)
    image: Annotated[str | None, NumToStr] = Field(default=None, max_length=100)


class Map(MapBase, DBModel, table=True):
    __tablename__ = "maps"
    # The import matches a map by short name
    __table_args__ = (
        Index("uq_maps_shortname", text("lower(trim(shortname))"), unique=True),
    )
    # deferred: only /maps/{id}/image reads the picture, every other map read leaves it in the database
    __mapper_args__ = {"properties": {"icon": deferred(icon_column)}}

    id: int | None = Field(default=None, primary_key=True)
    # The uploaded picture of the map; MapBase.image is the url the xlsx import fills
    icon: bytes | None = Field(default=None, sa_column=icon_column)
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

    status is `in_pool` when the season already plays it, `no_match` when
    warcraft3.info knows no map of that name and version, else `new`.
    """

    w3c_name: str
    matched_name: str | None = None
    shortname: str | None = None
    image_url: str | None = None
    status: str = "new"
