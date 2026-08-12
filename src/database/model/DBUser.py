from sqlalchemy import Column, Integer, String, Sequence, Enum, ForeignKey 
from sqlalchemy.orm import relationship
from src.database.model.DBModel import DBModel
from src.database.model.DBEnums import Race
from src.database.model.DBRelationships import DBUserTeamSeason

class DBUser(DBModel):
    __tablename__ = 'users'
    __table_args__ = {'mysql_charset': 'utf8mb4'}
    id = Column(Integer, Sequence(f'{__name__.lower()}_id_seq'), primary_key=True)
    name = Column(String(50), nullable=False)
    battleTag = Column(String(50), nullable=False)
    discordTag = Column(String(50), nullable=False)
    discordId = Column(String(50), nullable=False)
    race = Column(Enum(Race), nullable=False)
    mmr = Column(Integer)
    country = Column(String(2))
    fantasy_tier = Column(Integer)
    team_seasons = relationship('DBUserTeamSeason', back_populates='user', cascade="all, delete")
    w3c_stats = relationship("DBW3CStats", back_populates='user', cascade='all, delete-orphan')
    fantasy_teams = relationship("DBFantasyTeamPlayer", back_populates='users', cascade='all, delete-orphan')
    signup_seasons = relationship('DBUserSeasonSignup', back_populates='user', cascade="all, delete")


    @classmethod
    def updateUserTeamSeasonStats(cls, session, season_stats):
        from src.database.model.DBSeason import DBSeason
        from src.database.model.DBTeam import DBTeam
        team = session.query(DBTeam).filter_by(id=season_stats.team_id).first()
        if not team:
            raise Exception(f"Team not found by id: {season_stats.team_id}")
        season = session.query(DBSeason).filter_by(id=season_stats.season_id).first()
        if not season:
            raise Exception(f"Season not found by id: {season_stats.season_id}")
        user = session.query(cls).filter_by(id=season_stats.user_id).first()
        if not user:
            raise Exception(f"User not found by id: {season_stats.user_id}")
        uts_obj = session.query(DBUserTeamSeason).filter_by(team_id=team.id,season_id=season.id,user_id=user.id).first()
        if uts_obj is not None:
            uts_obj.games = season_stats.games
            uts_obj.wins = season_stats.wins
            uts_obj.losses = season_stats.losses
            uts_obj.matchup_history = season_stats.matchup_history
        else:
            uts_obj = DBUserTeamSeason(user=user,season=season,team=team)
            uts_obj.games = season_stats.games
            uts_obj.wins = season_stats.wins
            uts_obj.losses = season_stats.losses
            uts_obj.matchup_history = season_stats.matchup_history
            session.add(uts_obj)
        session.flush()
        return uts_obj
    


