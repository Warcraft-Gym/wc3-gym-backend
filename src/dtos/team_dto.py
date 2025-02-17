from src.database.model.DBTeam import DBTeam
from src.dtos.user_dto import UserDTO

class TeamDTO:
    def __init__(self, data : dict):
        self.id = data.get('id')
        self.name = data.get('name')
        self.player = data.get('player')
        self.season = data.get('season')

    def to_dict(self):
        l = []
        for p in self.player:
            l.append(p.to_dict())
        return {
            'id': self.id,
            'name': self.name,
            'player': l,
            'season': self.season
        }

    @classmethod
    def from_dbteam(cls, team: DBTeam):
        return cls(
                {
                'id' : team.id,
                'name' : team.name,
                'season' : team.season_id,
                'player' : UserDTO.from_dbuser_team(team.users)
            }
        )

    @staticmethod
    def schema():
        return {
            'type': 'object',
            'properties': {
                'id': {'type': 'integer'},
                'name': {'type': 'string'}
            },
            'required': ['name']
        }