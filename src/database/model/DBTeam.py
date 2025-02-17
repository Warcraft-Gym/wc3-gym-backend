from sqlalchemy import Column, Integer, String, Sequence, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.orm.session import Session
from src.database.model.DBModel import DBModel
from src.database.model.DBUser import DBUser
from src.database.model.DBRelationships import DBUserTeam
from src.database.model.DBSeason import DBSeason
from typing import List


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
        if team:
            users = session.query(DBUser).filter(DBUser.id.in_(user_ids)).all()
            for user in users:
                session.add(DBUserTeam(user=user,team=team))
            session.commit()
        return team