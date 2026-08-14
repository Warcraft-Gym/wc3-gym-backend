from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship

from app.models.base import DBModel

if TYPE_CHECKING:
    from app.models.relationships import DBMapSeason


class DBMap(DBModel, table=True):
    __tablename__ = "maps"
    id: int | None = Field(default=None, primary_key=True)
    name: str | None = Field(default=None, max_length=50)
    shortname: str | None = Field(default=None, max_length=50)
    image: str | None = Field(default=None, max_length=100)
    seasons: list["DBMapSeason"] = Relationship(
        back_populates="map", sa_relationship_kwargs={"cascade": "all, delete"}
    )

    def to_dict(self):
        return {
            column.name: getattr(self, column.name) for column in self.__table__.columns
        }
