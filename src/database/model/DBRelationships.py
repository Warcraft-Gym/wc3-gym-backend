from sqlalchemy import Column, Integer, String, Sequence, Enum, ForeignKey
from sqlalchemy.orm import relationship
from src.database.model.DBModel import DBModel

class DBUserTeamSeason(DBModel):
    __tablename__ = 'user_team_season'
    user_id = Column(Integer, ForeignKey('users.id'), primary_key=True)
    team_id = Column(Integer, ForeignKey('teams.id'), primary_key=True)
    season_id = Column(Integer, ForeignKey('seasons.id'), primary_key=True)
    # Additional columns can be added here if needed
    user = relationship('DBUser', back_populates='team_seasons')
    team = relationship('DBTeam', back_populates='user_seasons')
    season = relationship('DBSeason', back_populates='user_teams')

class DBTeamSeason(DBModel):
    __tablename__ = 'team_season'
    team_id = Column(Integer, ForeignKey('teams.id'), primary_key=True)
    season_id = Column(Integer, ForeignKey('seasons.id'), primary_key=True)
    # Additional columns can be added here if needed
    team = relationship('DBTeam', back_populates='season_info')
    season = relationship('DBSeason', back_populates='teams')
    final_score = Column(Integer)
    points_available = Column(Integer)
    points_against = Column(Integer)