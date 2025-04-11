from sqlalchemy import Column, Integer, String, Sequence, Enum, Float, ForeignKey
from sqlalchemy.orm import relationship
from src.database.model.DBModel import DBModel
from src.database.model.DBEnums import Race


class DBW3CStats(DBModel):
    __tablename__ = 'w3cstats'
    id = Column(Integer, Sequence(f'{__name__.lower()}_id_seq'), primary_key=True)
    wc3_season = Column(Integer, nullable=False)
    wins = Column(Integer)
    losses = Column(Integer)
    games = Column(Integer)
    mmr = Column(Integer)
    winrate = Column(Float)
    race = Column(Enum(Race))
    league = Column(Integer)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    user = relationship('DBUser', back_populates='w3c_stats')
