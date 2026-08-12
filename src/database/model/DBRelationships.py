from sqlalchemy import Column, Integer, String, Sequence, Enum, ForeignKey, Boolean, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.orm.session import Session
from src.database.model.DBModel import DBModel

class DBUserTeamSeason(DBModel):
    __tablename__ = 'user_team_season'
    user_id = Column(Integer, ForeignKey('users.id'), primary_key=True)
    team_id = Column(Integer, ForeignKey('teams.id'), primary_key=True)
    season_id = Column(Integer, ForeignKey('seasons.id'), primary_key=True)
    games = Column(Integer)
    wins = Column(Integer)
    losses = Column(Integer)
    matchup_history = Column(JSON, nullable=True)  # Array of opponent races: ['HU', 'OC', 'UD', etc.]
    # Additional columns can be added here if needed
    user = relationship('DBUser', back_populates='team_seasons')
    team = relationship('DBTeam', back_populates='user_seasons')
    season = relationship('DBSeason', back_populates='user_teams')

class DBUserSeasonSignup(DBModel):
    __tablename__ = 'user_season_signup'
    user_id = Column(Integer, ForeignKey('users.id'), primary_key=True)
    season_id = Column(Integer, ForeignKey('seasons.id'), primary_key=True)
    # Additional columns can be added here if needed
    user = relationship('DBUser', back_populates='signup_seasons')
    season = relationship('DBSeason', back_populates='signup_users')

class DBTeamSeason(DBModel):
    __tablename__ = 'team_season'
    team_id = Column(Integer, ForeignKey('teams.id'), primary_key=True)
    season_id = Column(Integer, ForeignKey('seasons.id'), primary_key=True)
    # Team coaches (up to 3)
    coach_1_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    coach_2_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    coach_3_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    # Additional columns
    final_score = Column(Integer)
    points_available = Column(Integer)
    points_against = Column(Integer)
    maps_won = Column(Integer)
    maps_lost = Column(Integer)
    # Relationships
    team = relationship('DBTeam', back_populates='season_info')
    season = relationship('DBSeason', back_populates='teams')
    coach_1 = relationship('DBUser', foreign_keys=[coach_1_id])
    coach_2 = relationship('DBUser', foreign_keys=[coach_2_id])
    coach_3 = relationship('DBUser', foreign_keys=[coach_3_id])

    @classmethod
    def updateSeasonInfo(cls, session: Session, obj_id, team_id, **kwargs):
        from sqlalchemy.orm import joinedload
        # Eager load related entities to prevent N+1 queries
        obj = session.query(cls)\
            .options(
                joinedload(cls.team),
                joinedload(cls.season)
            )\
            .filter_by(team_id=team_id, season_id=obj_id).first()
        if obj:
            for key, value in kwargs.items():
                setattr(obj, key, value)
            session.flush()
        return obj

class DBMapSeason(DBModel):
    __tablename__ = 'map_season'
    map_id = Column(Integer, ForeignKey('maps.id'), primary_key=True)
    season_id = Column(Integer, ForeignKey('seasons.id'), primary_key=True)
    season = relationship('DBSeason', back_populates='maps')
    map = relationship('DBMap', back_populates='seasons')

class DBFantasyTeamPlayer(DBModel):
    __tablename__ = 'fantasy_team_player'
    fantasy_team_id = Column(Integer, ForeignKey('fantasy_teams.id'), primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), primary_key=True)
    # Additional columns can be added here if needed
    fantasy_team = relationship('DBFantasyTeam', back_populates='drafted_players')
    users = relationship('DBUser', back_populates='fantasy_teams')
