from sqlalchemy import Column, Integer, String, Sequence, DateTime, Boolean
from sqlalchemy.orm import relationship
from src.database.model.DBModel import DBModel
from datetime import datetime

class DBKothEvent(DBModel):
    __tablename__ = 'koth_events'
    __table_args__ = {'mysql_charset': 'utf8mb4'}
    
    id = Column(Integer, Sequence(f'{__name__.lower()}_id_seq'), primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(String(500))
    event_date = Column(DateTime, nullable=False, default=datetime.utcnow)
    is_active = Column(Boolean, default=True, nullable=False)
    bracket_1_threshold = Column(Integer, default=1450, nullable=False)  # < this value
    bracket_2_threshold = Column(Integer, default=1600, nullable=False)  # >= bracket_1 and < this value
    # bracket 3 is >= bracket_2_threshold
    
    # Relationships
    signups = relationship('DBKothSignup', back_populates='event', cascade='all, delete-orphan')
    matches = relationship('DBKothMatch', back_populates='event', cascade='all, delete-orphan')
