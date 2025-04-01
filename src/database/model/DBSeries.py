from sqlalchemy import Column, Integer, String, Sequence, ForeignKey, DateTime, Boolean
from sqlalchemy.orm import relationship
from src.database.model.DBModel import DBModel

class DBSeries(DBModel):
    __tablename__ = 'series'
    id = Column(Integer, Sequence(f'{__name__.lower()}_id_seq'), primary_key=True)
    match_id = Column(Integer, ForeignKey('matches.id', ondelete='CASCADE'))
    date_time = Column(DateTime)
    caster = Column(String(50))
    player1_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'))
    player2_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'))
    player1_score = Column(Integer)
    player2_score = Column(Integer)
    player1_points = Column(Integer)
    player2_points = Column(Integer)
    host_player_id = Column(Integer)
    is_fantasy_match = Column(Boolean)

    match = relationship("DBMatch", foreign_keys=[match_id])
    player1 = relationship("DBUser", foreign_keys=[player1_id])
    player2 = relationship("DBUser", foreign_keys=[player2_id])

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}