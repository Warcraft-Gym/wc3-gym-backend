from sqlalchemy import Column, Integer, String, Sequence, Enum
from sqlalchemy.orm import relationship
from src.database.model.DBModel import DBModel
from src.database.model.DBEnums import Race, Country


class DBUser(DBModel):
    __tablename__ = 'users'
    id = Column(Integer, Sequence(f'{__name__.lower()}_id_seq'), primary_key=True)
    name = Column(String(50), nullable=False)
    battleTag = Column(String(50), nullable=False)
    discordTag = Column(String(50), nullable=False)
    race = Column(Enum(Race))
    mmr = Column(Integer)
    country = Column(Enum(Country))
    teams = relationship('DBUserTeam', back_populates='user')