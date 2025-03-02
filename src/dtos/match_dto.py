from src.database.model.DBMatch import DBMatch

class MatchDTO:
    def __init__(self, data : dict):
        self.id = data.get('id')
        self.team1_id = data.get('team1_id')
        self.team1 = data.get('team1')
        self.team2_id = data.get('team2_id')
        self.team2 = data.get('team2')
        self.score = data.get('score')

    def to_dict(self):
        return {
            'id': self.id,
            'team1_id': self.team1_id,
            'team1':self.team1,
            'team2_id': self.team2_id,
            'team2':self.team2,
            'score': self.score
        }
    
    def to_db_dict(self):
        return {
            'team1_id': self.team1_id,
            'team2_id': self.team2_id,
            'score': self.score
        }

    @classmethod
    def from_dbmatch(cls, match: DBMatch):
        return cls(
            {
                'id': match.id,
                'team1_id': match.team1_id,
                'team1': match.team1.name if match.team1 else None,
                'team2_id': match.team2_id,
                'team2': match.team2.name if match.team2 else None,
                'score': match.score
            }
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
