from sqlalchemy import Column, Integer, String, Sequence, ForeignKey
from sqlalchemy.orm import relationship
from src.database.model.DBModel import DBModel


class Match(DBModel):
    id = Column(Integer, Sequence(f'{__name__.lower()}_id_seq'), primary_key=True)
    team1_id = Column(Integer, ForeignKey('teams.id'))
    team2_id = Column(Integer, ForeignKey('teams.id'))
    score = Column(String(20))

    team1 = relationship("Team", foreign_keys=[team1_id])
    team2 = relationship("Team", foreign_keys=[team2_id])