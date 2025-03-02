from src.database.model.DBMatch import DBMatch

class MatchDTO:
    def __init__(self, id: int, team1_id: int, team1:str, team2_id: int,team2:str, score: str):
        self.id = id
        self.team1_id = team1_id
        self.team1 = team1
        self.team2_id = team2_id
        self.team2 = team2
        self.score = score

    def to_dict(self):
        return {
            'id': self.id,
            'team1_id': self.team1_id,
            'team1':self.team1,
            'team2_id': self.team2_id,
            'team2':self.team2,
            'score': self.score
        }

    @classmethod
    def from_dbmatch(cls, match: DBMatch):
        return cls(
            id=match.id,
            team1_id=match.team1_id,
            team1=match.team1.name,
            team2_id=match.team2_id,
            team2=match.team2.name,
            score=match.score
        )
    
    @staticmethod
    def schema():
        return {
            'type': 'object',
            'properties': {
                'team1_id': {'type': 'integer'},
                'team2_id': {'type': 'integer'},
                'score' : {'type': 'string'}
            },
            'required': ['team1_id','team2_id', 'score']
        }
