from sqlalchemy import Column, Integer, String, Sequence, Enum, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.orm.session import Session
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
    maps_won = Column(Integer)
    maps_lost = Column(Integer)

    @classmethod
    def updateSeasonInfo(cls, session: Session, season_id, team_id, **kwargs):
        obj = session.query(cls).filter_by(team_id=team_id, season_id=season_id).first()
        if obj:
            for key, value in kwargs.items():
                setattr(obj, key, value)
            session.commit()
        return obj

class DBMapSeason(DBModel):
    __tablename__ = 'map_season'
    map_id = Column(Integer, ForeignKey('maps.id'), primary_key=True)
    season_id = Column(Integer, ForeignKey('seasons.id'), primary_key=True)
    season = relationship('DBSeason', back_populates='maps')
    map = relationship('DBMap', back_populates='seasons')