from sqlalchemy import Column, Integer, String, Sequence, Enum, ForeignKey 
from sqlalchemy.orm import relationship
from src.database.model.DBModel import DBModel
from src.database.model.DBEnums import Race, Country
from src.database.model.DBRelationships import DBUserTeamSeason


class DBUser(DBModel):
    __tablename__ = 'users'
    __table_args__ = {'mysql_charset': 'utf8mb4'}
    id = Column(Integer, Sequence(f'{__name__.lower()}_id_seq'), primary_key=True)
    name = Column(String(50), nullable=False)
    battleTag = Column(String(50), nullable=False)
    discordTag = Column(String(50), nullable=False)
    race = Column(Enum(Race))
    mmr = Column(Integer)
    country = Column(Enum(Country))
    fantasy_tier = Column(Integer)
    team_seasons = relationship('DBUserTeamSeason', back_populates='user', cascade="all, delete")
    w3c_stats = relationship("DBW3CStats", back_populates='user', cascade='all, delete-orphan')
    fantasy_teams = relationship("DBFantasyTeamPlayer", back_populates='users', cascade='all, delete-orphan')