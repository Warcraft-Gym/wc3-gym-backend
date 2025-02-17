from sqlalchemy import create_engine, Column, Integer, String, Sequence
from src.database.model.DBModel import DBModel

class DBSeason(DBModel):
    __tablename__ = 'seasons'
    id = Column(Integer, Sequence(f'{__name__.lower()}_id_seq'), primary_key=True)
    name = Column(String(50))

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}