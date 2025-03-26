from sqlalchemy import Column, Integer, String, Sequence, ForeignKey
from sqlalchemy.orm import relationship
from src.database.model.DBModel import DBModel

class DBMap(DBModel):
    __tablename__ = 'maps'
    id = Column(Integer, Sequence(f'{__name__.lower()}_id_seq'), primary_key=True)
    name = Column(String(50))
    shortname = Column(String(50))
    image = Column(String(100))
    seasons = relationship('DBMapSeason', back_populates='map', cascade="all, delete")

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}