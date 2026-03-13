from src.database.model.DBDraftSeries import DBDraftSeries
from datetime import datetime
from src.dtos.match_dto import MatchDTO
from src.dtos.user_dto import UserDTO

class DraftSeriesDTO:
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
        self.player1_score = data.get('player1_score', 0)
        self.player2_score = data.get('player2_score', 0)
        self.host_player_id = data.get('host_player_id')
        self.is_fantasy_match = data.get('is_fantasy_match', False)
        self.created_at = data.get('created_at')

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
            'host_player_id': self.host_player_id,
            'is_fantasy_match': self.is_fantasy_match,
            'created_at': self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at
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
            'host_player_id': self.host_player_id,
            'is_fantasy_match': self.is_fantasy_match
        }
    
    @classmethod
    def from_db_draft_series(cls, draft_series: DBDraftSeries):
        if not draft_series:
            return None

        return cls(
            {
                'id': draft_series.id,
                'match_id': draft_series.match_id,
                'match': MatchDTO.from_dbmatch(draft_series.match) if draft_series.match else None,
                'date_time': draft_series.date_time,
                'caster': draft_series.caster,
                'player1_id': draft_series.player1_id,
                'player1': UserDTO.from_dbuser(draft_series.player1) if draft_series.player1 else None,
                'player2_id': draft_series.player2_id,
                'player2': UserDTO.from_dbuser(draft_series.player2) if draft_series.player2 else None,
                'player1_score': draft_series.player1_score,
                'player2_score': draft_series.player2_score,
                'host_player_id': draft_series.host_player_id,
                'is_fantasy_match': draft_series.is_fantasy_match,
                'created_at': draft_series.created_at
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
                'host_player_id': {'type': 'integer'},
                'is_fantasy_match': {'type': 'boolean'}
            },
            'required': ['match_id', 'player1_id', 'player2_id', 'host_player_id']
        }
