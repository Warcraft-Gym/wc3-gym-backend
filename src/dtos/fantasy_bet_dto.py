from src.database.model.DBFantasyBet import DBFantasyBet
from src.dtos.match_dto import MatchDTO
from src.dtos.user_dto import UserDTO

class FantasyBetDTO:
    def __init__(self, data: dict):
        self.id = data.get('id')
        self.series_id = data.get('series_id')
        self.series = data.get('series')
        self.user_id = data.get('user_id')
        self.user = data.get('user')
        self.winner_id = data.get('winner_id')
        self.winner = data.get('winner')
        self.bet_points = data.get('bet_points')
        self.bet_result = data.get('bet_result')

    def to_dict(self):
        return {
            'id': self.id,
            'series_id': self.series_id,
            'series': None if not self.series else self.series.to_dict(),
            'user_id': self.user_id,
            'user': None if not self.user else self.user.to_dict(),
            'winner_id': self.winner_id,
            'winner': None if not self.winner else self.winner.to_dict(),
            'bet_points': self.bet_points,
            'bet_result': self.bet_result
        }
    
    def to_db_dict(self):
        return {
            'series_id': self.series_id,
            'user_id': self.user_id,
            'winner_id': self.winner_id,
            'bet_points': self.bet_points,
            'bet_result': self.bet_result
        }
    
    @classmethod
    def from_dbfantasybet(cls, fbet: DBFantasyBet):
        return cls(
            {
                'id': fbet.id,
                'series_id': fbet.series_id,
                'series': MatchDTO.from_dbmatch(fbet.series),
                'user_id': fbet.user_id,
                'user_id': UserDTO.from_dbuser(fbet.user_id),
                'winner_id': fbet.winner_id,
                'winner': UserDTO.from_dbuser(fbet.winner),
                'bet_points': fbet.bet_points,
                'bet_result': fbet.bet_result
            }
        )
    
    @staticmethod
    def schema():
        return {
            'type': 'object',
            'properties': {
                'series_id': {'type': 'integer'},
                'user_id': {'type': 'integer'},
                'winner_id': {'type': 'integer'},
                'bet_score': {'type': 'integer'},
                'bet_result': {'type': 'integer'}
            },
            'required': ['series_id', 'user_id', 'winner_id', 'bet_score']
        }