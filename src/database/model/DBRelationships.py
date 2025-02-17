from sqlalchemy import Column, Integer, String, Sequence, Enum, ForeignKey
from sqlalchemy.orm import relationship
from src.database.model.DBModel import DBModel

class DBUserTeam(DBModel):
    __tablename__ = 'user_team'
    user_id = Column(Integer, ForeignKey('users.id'), primary_key=True)
    team_id = Column(Integer, ForeignKey('teams.id'), primary_key=True)
    user = relationship('DBUser', back_populates='teams')
    team = relationship('DBTeam', back_populates='users')