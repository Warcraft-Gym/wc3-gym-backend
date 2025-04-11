from sqlalchemy import Column, Integer, String, Sequence, ForeignKey, DateTime, Boolean
from sqlalchemy.orm import relationship
from src.database.model.DBModel import DBModel

class DBFantasyBet(DBModel):
    __tablename__ = 'fantasy_bets'
    id = Column(Integer, Sequence(f'{__name__.lower()}_id_seq'), primary_key=True)
    season_id = Column(Integer, ForeignKey('seasons.id', ondelete='CASCADE'),  nullable=False)
    series_id = Column(Integer, ForeignKey('series.id', ondelete='CASCADE'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    winner_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    bet_points = Column(Integer, nullable=False)
    bet_result = Column(Integer)

    season = relationship("DBSeason", foreign_keys=[season_id])
    series = relationship("DBSeries", foreign_keys=[series_id])
    user = relationship("DBUser", foreign_keys=[user_id])
    winner = relationship("DBUser", foreign_keys=[winner_id])

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}