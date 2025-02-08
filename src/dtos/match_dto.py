class MatchDTO:
    def __init__(self, id: int, team1_id: int, team2_id: int, score: str):
        self.id = id
        self.team1_id = team1_id
        self.team2_id = team2_id
        self.score = score

    def to_dict(self):
        return {
            'id': self.id,
            'team1_id': self.team1_id,
            'team2_id': self.team2_id,
            'score': self.score
        }

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            id=data.get('id'),
            team1_id=data.get('team1_id'),
            team2_id=data.get('team2_id'),
            score=data.get('score')
        )
