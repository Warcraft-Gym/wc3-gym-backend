from src.database.model.DBSeries import DBSeries
from src.dtos.match_dto import MatchDTO
from src.dtos.user_dto import UserDTO

class SeriesDTO:
    def __init__(self, data: dict):
        self.id = data.get('id')
        self.match_id = data.get('match_id')
        self.match = data.get('match')
        self.player1_id = data.get('player1_id')
        self.player1 = data.get('player1')
        self.player2_id = data.get('player2_id')
        self.player2 = data.get('player2')
        self.score = data.get('score')

    def to_dict(self):
        return {
            'id': self.id,
            'match_id': self.match_id,
            'match': None if not self.match else self.match.to_dict(),
            'player1_id': self.player1_id,
            'player1': None if not self.player1 else self.player1.to_dict(),
            'player2_id': self.player2_id,
            'player2': None if not self.player2 else self.player2.to_dict(),
            'score': self.score
        }
    
    def to_db_dict(self):
        return {
            'match_id': self.match_id,
            'player1_id': self.player1_id,
            'player2_id': self.player2_id,
            'score': self.score
        }
    
    @classmethod
    def from_dbseries(cls, series: DBSeries):
        return cls(
            {
                'id': series.id,
                'match_id': series.match_id,
                'match': MatchDTO.from_dbmatch(series.match),
                'player1_id': series.player1_id,
                'player1': UserDTO.from_dbuser(series.player1),
                'player2_id': series.player2_id,
                'player2': UserDTO.from_dbuser(series.player2),
                'score': series.score
            }
        )
    
    @staticmethod
    def schema():
        return {
            'type': 'object',
            'properties': {
                'match_id': {'type': 'integer'},
                'player1_id': {'type': 'integer'},
                'player2_id': {'type': 'integer'}
            },
            'required': ['match_id', 'player1_id', 'player2_id']
        }