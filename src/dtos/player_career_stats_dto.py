from src.database.model.DBPlayerCareerStats import DBPlayerCareerStats
from src.dtos.user_dto import UserDTO

class PlayerCareerStatsDTO:
    def __init__(self, data: dict):
        self.id = data.get('id')
        self.user_id = data.get('user_id')
        self.player_name = data.get('player_name')
        self.user = data.get('user')
        # Historical baseline
        self.historical_rating = data.get('historical_rating')
        self.historical_series_won = data.get('historical_series_won')
        self.historical_series_lost = data.get('historical_series_lost')
        self.historical_games_won = data.get('historical_games_won')
        self.historical_games_lost = data.get('historical_games_lost')
        self.historical_seasons_played = data.get('historical_seasons_played')
        # Combined totals
        self.rating = data.get('rating')
        self.series_won = data.get('series_won')
        self.series_lost = data.get('series_lost')
        self.series_winrate = data.get('series_winrate')
        self.games_won = data.get('games_won')
        self.games_lost = data.get('games_lost')
        self.games_winrate = data.get('games_winrate')
        self.seasons_played = data.get('seasons_played')
        self.avg_series_per_season = data.get('avg_series_per_season')

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'player_name': self.player_name,
            'user': None if not self.user else self.user.to_dict(),
            # Historical baseline
            'historical_rating': self.historical_rating,
            'historical_series_won': self.historical_series_won,
            'historical_series_lost': self.historical_series_lost,
            'historical_games_won': self.historical_games_won,
            'historical_games_lost': self.historical_games_lost,
            'historical_seasons_played': self.historical_seasons_played,
            # Combined totals
            'rating': self.rating,
            'series_won': self.series_won,
            'series_lost': self.series_lost,
            'series_winrate': float(self.series_winrate) if self.series_winrate else 0.0,
            'games_won': self.games_won,
            'games_lost': self.games_lost,
            'games_winrate': float(self.games_winrate) if self.games_winrate else 0.0,
            'seasons_played': self.seasons_played,
            'avg_series_per_season': float(self.avg_series_per_season) if self.avg_series_per_season else 0.0
        }
    
    def to_db_dict(self):
        """Convert DTO to dictionary for DB operations (excludes id and relationships)"""
        return {
            'user_id': self.user_id,
            'player_name': self.player_name,
            'historical_rating': self.historical_rating,
            'historical_series_won': self.historical_series_won,
            'historical_series_lost': self.historical_series_lost,
            'historical_games_won': self.historical_games_won,
            'historical_games_lost': self.historical_games_lost,
            'historical_seasons_played': self.historical_seasons_played,
            'rating': self.rating,
            'series_won': self.series_won,
            'series_lost': self.series_lost,
            'series_winrate': self.series_winrate,
            'games_won': self.games_won,
            'games_lost': self.games_lost,
            'games_winrate': self.games_winrate,
            'seasons_played': self.seasons_played,
            'avg_series_per_season': self.avg_series_per_season
        }

    @classmethod
    def from_db(cls, stats: DBPlayerCareerStats):
        if not stats:
            return None
        
        return cls({
            'id': stats.id,
            'user_id': stats.user_id,
            'player_name': stats.player_name,
            'user': UserDTO.from_dbuser(stats.user) if stats.user else None,
            # Historical baseline
            'historical_rating': stats.historical_rating,
            'historical_series_won': stats.historical_series_won,
            'historical_series_lost': stats.historical_series_lost,
            'historical_games_won': stats.historical_games_won,
            'historical_games_lost': stats.historical_games_lost,
            'historical_seasons_played': stats.historical_seasons_played,
            # Combined totals
            'rating': stats.rating,
            'series_won': stats.series_won,
            'series_lost': stats.series_lost,
            'series_winrate': stats.series_winrate,
            'games_won': stats.games_won,
            'games_lost': stats.games_lost,
            'games_winrate': stats.games_winrate,
            'seasons_played': stats.seasons_played,
            'avg_series_per_season': stats.avg_series_per_season
        })

    @staticmethod
    def schema():
        return {
            'type': 'object',
            'properties': {
                'user_id': {'type': 'integer'},
                'player_name': {'type': 'string'},
                'historical_rating': {'type': 'integer'},
                'historical_series_won': {'type': 'integer'},
                'historical_series_lost': {'type': 'integer'},
                'historical_games_won': {'type': 'integer'},
                'historical_games_lost': {'type': 'integer'},
                'historical_seasons_played': {'type': 'integer'},
                'rating': {'type': 'integer'},
                'series_won': {'type': 'integer'},
                'series_lost': {'type': 'integer'},
                'series_winrate': {'type': 'number'},
                'games_won': {'type': 'integer'},
                'games_lost': {'type': 'integer'},
                'games_winrate': {'type': 'number'},
                'seasons_played': {'type': 'integer'},
                'avg_series_per_season': {'type': 'number'}
            },
            'required': ['player_name']
        }
