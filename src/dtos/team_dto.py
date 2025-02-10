from src.database.model.DBTeam import DBTeam

class TeamDTO:
    def __init__(self, id: int, name: str):
        self.id = id
        self.name = name

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name
        }

    @classmethod
    def from_dbteam(cls, team: DBTeam):
        return cls(
            id=team.id,
            name=team.name
        )
