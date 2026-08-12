from sqlalchemy import Column, Integer, String, Sequence, ForeignKey, Enum
from sqlalchemy.orm import relationship
from src.database.model.DBEnums import Race
from src.database.model.DBModel import DBModel
from src.database.model.DBUser import DBUser
from src.database.model.DBRelationships import DBFantasyTeamPlayer
from sqlalchemy.orm.session import Session

class DBFantasyTeam(DBModel):
    __tablename__ = 'fantasy_teams'
    id = Column(Integer, Sequence(f'{__name__.lower()}_id_seq'), primary_key=True)
    name = Column(String(100), nullable=False)
    season_id = Column(Integer, ForeignKey('seasons.id', ondelete='CASCADE'), nullable=False)
    captain_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    drafted_team_id = Column(Integer, ForeignKey('teams.id', ondelete='CASCADE'))
    drafted_race = Column(Enum(Race))
    player_points = Column(Integer)
    bench_points = Column(Integer)
    team_points = Column(Integer)
    race_points = Column(Integer)
    bet_points = Column(Integer)
    total_points = Column(Integer)

    drafted_team = relationship("DBTeam", foreign_keys=[drafted_team_id])
    captain = relationship("DBUser", foreign_keys=[captain_id])
    season = relationship("DBSeason", foreign_keys=[season_id])
    drafted_players = relationship("DBFantasyTeamPlayer", back_populates='fantasy_team', cascade="all, delete")

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
    

    @classmethod
    def addPlayers(cls, session: Session, obj_id, user_ids):
        team = session.query(cls).filter_by(id=obj_id).first()
        if not team:
            raise Exception(f"Team not found by id: {obj_id}")
        for user_id in user_ids:
            user = session.query(DBUser).filter_by(id=user_id).first()
            if not user:
                raise Exception(f"User not found by id: {user_id}")
            already_exists = session.query(DBFantasyTeamPlayer).filter_by(fantasy_team_id=team.id,user_id=user.id).first() is not None
            if not already_exists:
                session.add(DBFantasyTeamPlayer(users=user,fantasy_team=team)) 
                         
        session.flush()
        return team
    

    @classmethod
    def removePlayers(cls, session: Session, obj_id, user_ids):
        team = session.query(cls).filter_by(id=obj_id).first()
        if not team:
            raise Exception(f"Fantasy Team not found by id: {obj_id}")
        for user_id in user_ids:
            user = session.query(DBUser).filter_by(id=user_id).first()
            if not user:
                raise Exception(f"User not found by id: {user_id}")
            user_team = session.query(DBFantasyTeamPlayer).filter_by(fantasy_team_id=obj_id,user_id=user.id).first()
            if not user_team:
                raise Exception(f"User not part of the fantasy team, user id: {user_id}")
            session.delete(user_team)                
        session.flush()
        return team