from sqlalchemy import create_engine, Column, Integer, String, Sequence
from src.database.model.DBModel import DBModel


class Team(DBModel):
    id = Column(Integer, Sequence(f'{__name__.lower()}_id_seq'), primary_key=True)
    name = Column(String(50))