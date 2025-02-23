from sqlalchemy import Column, Integer, String, Sequence, ForeignKey
from sqlalchemy.orm import relationship
from src.database.model.DBModel import DBModel

class DBSeries(DBModel):
    __tablename__ = 'series'
    id = Column(Integer, Sequence(f'{__name__.lower()}_id_seq'), primary_key=True)
    match_id = Column(Integer, ForeignKey('matches.id'))
    player1_id = Column(Integer, ForeignKey('users.id'))
    player2_id = Column(Integer, ForeignKey('users.id'))
    score = Column(String(20))

    match = relationship("DBMatch", foreign_keys=[match_id])
    player1 = relationship("DBUser", foreign_keys=[player1_id])
    player2 = relationship("DBUser", foreign_keys=[player2_id])

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}