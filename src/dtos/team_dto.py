from src.database.model.DBTeam import DBTeam
from src.dtos.user_dto import UserDTO
from src.dtos.season_info_dto import SeasonInfoDTO

class TeamDTO:
    def __init__(self, data : dict):
        self.id = data.get('id')
        self.name = data.get('name')
        self.player_by_season = data.get('player_by_season')
        self.seasons_info = data.get('seasons_info')

    def to_dict(self):
        l = {}
        if self.player_by_season:
            for season, players in self.player_by_season.items():
                if players:
                    l[season] = [player.to_dict() for player in players]
        seasons_info = [seasons_info.to_dict() for seasons_info in self.seasons_info]
        return {
            'id': self.id,
            'name': self.name,
            'player_by_season': l,
            'seasons_info': seasons_info
        }
    
    def to_db_dict(self):
        return {
            'id': self.id,
            'name': self.name
        }

    @classmethod
    def from_dbteam(cls, team: DBTeam):
        u = {}
        seasons_info = [SeasonInfoDTO.from_dbseasoninfo(season_info) for season_info in team.season_info ]

        for ut in team.user_seasons:
            if not u.get(ut.season_id):
                u[ut.season_id]=[]
            u.get(ut.season_id).append(UserDTO.from_dbuser(ut.user))

        return cls(
                {
                'id' : team.id,
                'name' : team.name,
                'player_by_season' : u,
                'seasons_info' : seasons_info
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