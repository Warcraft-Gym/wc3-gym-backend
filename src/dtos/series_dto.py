from src.database.model.DBSeries import DBSeries
from src.dtos.match_dto import MatchDTO
from src.dtos.user_dto import UserDTO

class SeriesDTO:
    def __init__(self, data: dict):
        self.id = id
        self.match = match
        self.player1 = player1
        self.player2 = player2
        self.score = score

    def to_dict(self):
        return {
            'id': self.id,
            'match': None if not self.match else self.match.to_dict(),
            'player1': None if not self.player1 else self.player1.to_dict(),
            'player2': None if not self.player2 else self.player2.to_dict(),
            'score': self.score
        }
    
    @classmethod
    def from_dbseries(cls, series: DBSeries):
        return cls(
            id=series.id,
            match=MatchDTO.from_dbmatch(series.match),
            player1=UserDTO.from_dbuser(series.player1),
            player2=UserDTO.from_dbuser(series.player2),
            score=series.score
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