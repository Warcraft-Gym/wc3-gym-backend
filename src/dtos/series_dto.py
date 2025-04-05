from src.database.model.DBSeries import DBSeries
from datetime import datetime
from src.dtos.match_dto import MatchDTO
from src.dtos.user_dto import UserDTO

class SeriesDTO:
    def __init__(self, data: dict):
        self.id = data.get('id')
        self.match_id = data.get('match_id')
        self.match = data.get('match')
        dt = data.get('date_time')
        if dt and isinstance(dt, str):
            dt = datetime.fromisoformat(dt)
        self.date_time = dt
        self.caster = data.get('caster')
        self.player1_id = data.get('player1_id')
        self.player1 = data.get('player1')
        self.player2_id = data.get('player2_id')
        self.player2 = data.get('player2')
        self.player1_score = data.get('player1_score')
        self.player2_score = data.get('player2_score')
        self.player1_points = data.get('player2_points')
        self.player2_points = data.get('player2_points')
        self.host_player_id = data.get('host_player_id')

    def to_dict(self):
        return {
            'id': self.id,
            'match_id': self.match_id,
            'match': None if not self.match else self.match.to_dict(),
            'date_time': self.date_time.isoformat() if isinstance(self.date_time, datetime) else self.date_time,
            'caster': self.caster,
            'player1_id': self.player1_id,
            'player1': None if not self.player1 else self.player1.to_dict(),
            'player2_id': self.player2_id,
            'player2': None if not self.player2 else self.player2.to_dict(),
            'player1_score': self.player1_score,
            'player2_score': self.player2_score,
            'player1_points': self.player1_points,
            'player2_points': self.player2_points,
            'host_player_id': self.host_player_id
        }
    
    def to_db_dict(self):
        return {
            'match_id': self.match_id,
            'date_time': self.date_time,
            'caster': self.caster,
            'player1_id': self.player1_id,
            'player2_id': self.player2_id,
            'player1_score': self.player1_score,
            'player2_score': self.player2_score,
            'player1_points': self.player1_points,
            'player2_points': self.player2_points,
            'host_player_id': self.host_player_id
        }
    
    @classmethod
    def from_dbseries(cls, series: DBSeries):
        return cls(
            {
                'id': series.id,
                'match_id': series.match_id,
                'match': MatchDTO.from_dbmatch(series.match),
                'date_time': series.date_time,
                'caster': series.caster,
                'player1_id': series.player1_id,
                'player1': UserDTO.from_dbuser(series.player1),
                'player2_id': series.player2_id,
                'player2': UserDTO.from_dbuser(series.player2),
                'player1_score': series.player1_score,
                'player2_score': series.player2_score,
                'player1_points': series.player1_points,
                'player2_points': series.player2_points,
                'host_player_id': series.host_player_id
            }
        )
    
    @staticmethod
    def schema():
        return {
            'type': 'object',
            'properties': {
                'match_id': {'type': 'integer'},
                'date_time': {'type': 'string', 'format':'date-time', 'description': 'ISO 8601 date-time (e.g., "2025-03-08T18:57:00Z")'},
                'caster': {'type': 'string'},
                'player1_id': {'type': 'integer'},
                'player2_id': {'type': 'integer'},
                'player1_score': {'type': 'integer'},
                'player2_score': {'type': 'integer'},
                'player1_points': {'type': 'integer'},
                'player2_points': {'type': 'integer'},
                'host_player_id': {'type': 'integer'}
            },
            'required': ['match_id', 'player1_id', 'player2_id']
        }