from sqlalchemy import Column, Integer, String, Sequence, ForeignKey, DateTime, Boolean, or_, and_
from sqlalchemy.orm import relationship
from src.database.model.DBModel import DBModel
from src.database.model.DBMatch import DBMatch
from sqlalchemy.orm.session import Session
from custom_exceptions import DBException

class DBSeries(DBModel):
    __tablename__ = 'series'
    id = Column(Integer, Sequence(f'{__name__.lower()}_id_seq'), primary_key=True)
    match_id = Column(Integer, ForeignKey('matches.id', ondelete='CASCADE'), nullable=False)
    date_time = Column(DateTime)
    caster = Column(String(50))
    player1_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    player2_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    player1_score = Column(Integer)
    player2_score = Column(Integer)
    player1_points = Column(Integer)
    player2_points = Column(Integer)
    host_player_id = Column(Integer, nullable=False)
    is_fantasy_match = Column(Boolean)

    match = relationship("DBMatch", foreign_keys=[match_id])
    player1 = relationship("DBUser", foreign_keys=[player1_id])
    player2 = relationship("DBUser", foreign_keys=[player2_id])

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
    
    @classmethod
    def searchForSeasonAndPlayday(cls, session: Session, season_id, playday, filters):
        query = None
        if filters is None:
            query = session.query(cls).filter(cls.match.has(and_(DBMatch.season_id == season_id, DBMatch.playday == playday)))
        else:
            query = session.query(cls).filter(cls.match.has(and_(DBMatch.season_id == season_id, DBMatch.playday == playday))).filter(filters)
        return query.all()
    
    @classmethod
    def searchForSeason(cls, session: Session, season_id, filters):
        query = None
        if filters is None:
            query = session.query(cls).filter(cls.match.has(DBMatch.season_id == season_id))
        else:
            query = session.query(cls).filter(cls.match.has(DBMatch.season_id == season_id)).filter(filters)
        return query.all()