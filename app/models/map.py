from typing import TYPE_CHECKING, Annotated, Any

from sqlmodel import Field, Relationship, SQLModel

from app.models.base import DBModel
from app.models.types import NumToStr

if TYPE_CHECKING:
    from app.models.relationships import DBMapSeason


class MapBase(SQLModel):
    # The xlsx import passes these cells straight through, so a numeric
    # map name or shortname arrives as a number.
    name: Annotated[str | None, NumToStr] = Field(default=None, max_length=50)
    shortname: Annotated[str | None, NumToStr] = Field(default=None, max_length=50)
    image: Annotated[str | None, NumToStr] = Field(default=None, max_length=100)


class Map(MapBase, DBModel, table=True):
    __tablename__ = "maps"

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

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
