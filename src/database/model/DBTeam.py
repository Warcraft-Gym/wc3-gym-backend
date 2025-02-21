from sqlalchemy import Column, Integer, String, Sequence, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.orm.session import Session
from src.database.model.DBModel import DBModel
from src.database.model.DBUser import DBUser
from src.database.model.DBRelationships import DBUserTeam


class DBTeam(DBModel):
    __tablename__ = 'teams'
    id = Column(Integer, Sequence(f'{__name__.lower()}_id_seq'), primary_key=True)
    name = Column(String(50))
    icon = Column(String(50))
    season_id = Column(Integer, ForeignKey('seasons.id'))
    season = relationship("DBSeason", foreign_keys=[season_id])
    users = relationship('DBUserTeam', back_populates='team')

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
            already_exists = session.query(DBUserTeam).filter_by(team_id=team.id,user_id=user.id).first() is not None
            if already_exists:
                raise Exception(f"User already part of the team, user id: {user_id}")
            session.add(DBUserTeam(user=user,team=team))              
        session.commit()
        return team

    @classmethod
    def removePlayers(cls, session: Session, obj_id, user_ids):
        team = session.query(cls).filter_by(id=obj_id).first()
        if not team:
            raise Exception(f"Team not found by id: {obj_id}")
        for user_id in user_ids:
            user = session.query(DBUser).filter_by(id=user_id).first()
            if not user:
                raise Exception(f"User not found by id: {user_id}")
            user_team = session.query(DBUserTeam).filter_by(team_id=team.id,user_id=user.id).first()
            if not user_team:
                raise Exception(f"User not part of the team, user id: {user_id}")
            session.delete(user_team)                
        session.commit()
        return team