from src.database.model.DBTeam import DBTeam
from src.dtos.user_dto import UserDTO
from src.dtos.season_info_dto import SeasonInfoDTO
from src.dtos.user_team_season_stats_dto import UserTeamSeasonStatsDTO
from src.dtos.season_dto import SeasonDTO

class TeamDTO:
    def __init__(self, data : dict):
        self.id = data.get('id')
        self.name = data.get('name')
        self.long_name = data.get('long_name')
        self.discord_role = data.get('discord_role')
        self.player_by_season = data.get('player_by_season')
        self.seasons_info = data.get('seasons_info')

    def to_dict(self):
        l = {}
        if self.player_by_season:
            for season, players in self.player_by_season.items():
                if players:
                    l[season] = [player.to_dict() for player in players if player]
        seasons_info = [seasons_info.to_dict() for seasons_info in self.seasons_info if seasons_info] if self.seasons_info else []
        return {
            'id': self.id,
            'name': self.name,
            'long_name': self.long_name,
            'discord_role': self.discord_role,
            'player_by_season': l,
            'seasons_info': seasons_info
        }
    
    def to_dict_reduced(self):
        return {
            'id': self.id,
            'name': self.name,
            'long_name': self.long_name,
            'discord_role': self.discord_role
        }
    
    def to_db_dict(self):
        return {
            'name': self.name,
            'long_name': self.long_name,
            'discord_role': self.discord_role
        }

    @classmethod
    def from_dbteam(cls, team: DBTeam):
        if not team:
            return None

        u = {}
        seasons_info = [s for s in (SeasonInfoDTO.from_dbseasoninfo(info) for info in team.season_info) if s] if team.season_info else []

        if team.user_seasons:
            for ut in team.user_seasons:
                if not u.get(ut.season_id):
                    u[ut.season_id]=[]
                user = UserDTO.from_dbuser(ut.user)
                if user:
                    for gnl_stat in user.gnl_stats:
                        if (gnl_stat.season_id==ut.season_id):
                            user.gnl_stats = [gnl_stat]
                            break
                    u.get(ut.season_id).append(user)

        return cls(
                {
                'id' : team.id,
                'name' : team.name,
                'long_name': team.long_name,
                'discord_role': team.discord_role,
                'player_by_season' : u,
                'seasons_info' : seasons_info
            }
        )

    @classmethod
    def from_dbteam_reduced(cls, team: DBTeam):
        return cls(
                {
                'id' : team.id,
                'name' : team.name,
                'long_name': team.long_name,
                'discord_role': team.discord_role
            }
        )
    

    @staticmethod
    def schema():
        return {
            'type': 'object',
            'properties': {
                'name': {'type': 'string'},
                'long_name': {'type': 'string'},
                'discord_role': {'type': 'string'}
            },
            'required': ['name']
        }