from src.database.model.DBTeam import DBTeam
from src.dtos.user_dto import UserDTO
from src.dtos.season_dto import SeasonDTO

class TeamDTO:
    def __init__(self, data : dict):
        self.id = data.get('id')
        self.name = data.get('name')
        self.player = data.get('player')
        self.season = data.get('season')

    def to_dict(self):
        l = []
        if self.player:
            for p in self.player:
                l.append(p.to_dict())
        return {
            'id': self.id,
            'name': self.name,
            'player': l,
            'season': None if not self.season else self.season.to_dict()
        }
    
    def to_db_dict(self):
        return {
            'id': self.id,
            'name': self.name
        }

    @classmethod
    def from_dbteam(cls, team: DBTeam):
        return cls(
                {
                'id' : team.id,
                'name' : team.name,
                'season' : SeasonDTO.from_dbseason(team.season),
                'player' : UserDTO.from_dbuser_team(team.users)
            }
        )

    @staticmethod
    def schema():
        return {
            'type': 'object',
            'properties': {
                'name': {'type': 'string'}
            },
            'required': ['name']
        }