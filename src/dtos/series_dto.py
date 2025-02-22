from src.database.model.DBSeries import DBSeries

class SeriesDTO:
    def __init__(self, id: int, match_id: int, match: str, player1_id: int, player1:str, player2_id: int, player2:str, score: str):
        self.id = id
        self.match_id = match_id
        self.match = match
        self.player1_id = player1_id
        self.player1 = player1
        self.player2_id = player2_id
        self.player2 = player2
        self.score = score

    def to_dict(self):
        return {
            'id': self.id,
            'match_id': self.match_id,
            'match': self.match,
            'player1_id': self.player1_id,
            'player1': self.player1,
            'player2_id': self.player2_id,
            'player2': self.player2,
            'score': self.score
        }
    
    @classmethod
    def from_dbseries(cls, series: DBSeries):
        return cls(
            id=series.id,
            match_id=series.match_id,
            match=series.match,
            player1_id=series.player1_id,
            player1=series.player1,
            player2_id=series.player2_id,
            player2=series.player2,
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