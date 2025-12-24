from sqlalchemy import Column, Integer, String, Sequence, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from src.database.model.DBModel import DBModel
from datetime import datetime

class DBKothMatch(DBModel):
    __tablename__ = 'koth_matches'
    __table_args__ = {'mysql_charset': 'utf8mb4'}
    
    id = Column(Integer, Sequence(f'{__name__.lower()}_id_seq'), primary_key=True)
    event_id = Column(Integer, ForeignKey('koth_events.id'), nullable=False)
    bracket = Column(Integer, nullable=False)  # 1, 2, or 3
    game_mode = Column(String(50), nullable=False)  # e.g., "1v1", "2v1", "2v2", "3v1", "FFA", "Custom"
    num_teams = Column(Integer, nullable=False)  # Number of teams in the match
    winner_team_number = Column(Integer)  # Team number that won (1, 2, 3, etc.), null until match complete
    
    # Relationships
    event = relationship('DBKothEvent', back_populates='matches')
    participants = relationship('DBKothMatchParticipant', back_populates='match', cascade='all, delete-orphan')
