from sqlalchemy import Column, Integer, String, Sequence, ForeignKey, Enum, DateTime
from sqlalchemy.orm import relationship
from src.database.model.DBModel import DBModel
from src.database.model.DBEnums import Race
from datetime import datetime

class DBKothSignup(DBModel):
    __tablename__ = 'koth_signups'
    __table_args__ = {'mysql_charset': 'utf8mb4'}
    
    id = Column(Integer, Sequence(f'{__name__.lower()}_id_seq'), primary_key=True)
    event_id = Column(Integer, ForeignKey('koth_events.id'), nullable=False)
    twitch_username = Column(String(50), nullable=True)  # Optional Twitch username
    battle_tag = Column(String(50), nullable=False)  # Can signup multiple times
    w3c_name = Column(String(50), nullable=False)
    race = Column(Enum(Race), nullable=False)
    mmr = Column(Integer, nullable=False)  # MMR at time of signup (avg of last 3 seasons)
    bracket = Column(Integer, nullable=False)  # 1, 2, or 3
    is_king = Column(Integer, default=0, nullable=False)  # 0=no, 1=yes
    is_active = Column(Integer, default=1, nullable=False)  # 0=inactive, 1=active
    
    # Relationships
    event = relationship('DBKothEvent', back_populates='signups')
    match_participations = relationship('DBKothMatchParticipant', back_populates='signup', cascade='all, delete-orphan')
