from sqlalchemy import Column, Integer, Sequence, ForeignKey
from sqlalchemy.orm import relationship
from src.database.model.DBModel import DBModel

class DBKothMatchParticipant(DBModel):
    __tablename__ = 'koth_match_participants'
    __table_args__ = {'mysql_charset': 'utf8mb4'}
    
    id = Column(Integer, Sequence(f'{__name__.lower()}_id_seq'), primary_key=True)
    match_id = Column(Integer, ForeignKey('koth_matches.id'), nullable=False)
    signup_id = Column(Integer, ForeignKey('koth_signups.id'), nullable=False)
    team_number = Column(Integer, nullable=False)  # Which team this player is on (1, 2, 3, etc.)
    
    # Relationships
    match = relationship('DBKothMatch', back_populates='participants')
    signup = relationship('DBKothSignup', back_populates='match_participations')
