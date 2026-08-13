from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.models.base import DBModel

class DBMap(DBModel):
    __tablename__ = 'maps'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str | None] = mapped_column(String(50))
    shortname: Mapped[str | None] = mapped_column(String(50))
    image: Mapped[str | None] = mapped_column(String(100))
    seasons: Mapped[list['DBMapSeason']] = relationship(back_populates='map', cascade="all, delete")

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
