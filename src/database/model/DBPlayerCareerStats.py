from sqlalchemy import Column, Integer, DECIMAL, Boolean, TIMESTAMP, ForeignKey, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from src.database.model.DBModel import DBModel

class DBPlayerCareerStats(DBModel):
    __tablename__ = 'player_career_stats'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    player_name = Column(String(255), nullable=False, unique=True)
    
    # Historical baseline (imported from CSV, immutable)
    historical_rating = Column(Integer, default=0)
    historical_series_won = Column(Integer, default=0)
    historical_series_lost = Column(Integer, default=0)
    historical_games_won = Column(Integer, default=0)
    historical_games_lost = Column(Integer, default=0)
    historical_seasons_played = Column(Integer, default=0)
    
    # Combined totals (historical + calculated, for display)
    rating = Column(Integer, default=0)
    series_won = Column(Integer, default=0)
    series_lost = Column(Integer, default=0)
    series_winrate = Column(DECIMAL(5, 2), default=0.00)
    games_won = Column(Integer, default=0)
    games_lost = Column(Integer, default=0)
    games_winrate = Column(DECIMAL(5, 2), default=0.00)
    seasons_played = Column(Integer, default=0)
    avg_series_per_season = Column(DECIMAL(5, 2), default=0.00)
    
    # Relationships
    user = relationship("DBUser", backref="career_stats")
    
    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
