from sqlalchemy import Column, Integer, String, Sequence, ForeignKey, DateTime, Boolean, TIMESTAMP
from sqlalchemy.orm import relationship
from src.database.model.DBModel import DBModel
from src.database.model.DBMatch import DBMatch
from sqlalchemy.orm.session import Session

class DBDraftSeries(DBModel):
    __tablename__ = 'draft_series'
    id = Column(Integer, Sequence(f'{__name__.lower()}_id_seq'), primary_key=True)
    match_id = Column(Integer, ForeignKey('matches.id'), nullable=False)
    date_time = Column(DateTime)
    caster = Column(String(50))
    player1_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    player2_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    player1_score = Column(Integer, default=0)
    player2_score = Column(Integer, default=0)
    host_player_id = Column(Integer, nullable=False)
    is_fantasy_match = Column(Boolean, default=False)
    created_at = Column(TIMESTAMP)

    match = relationship("DBMatch", foreign_keys=[match_id])
    player1 = relationship("DBUser", foreign_keys=[player1_id])
    player2 = relationship("DBUser", foreign_keys=[player2_id])

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
