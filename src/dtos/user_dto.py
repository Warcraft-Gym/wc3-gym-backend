from src.database.model.DBUser import DBUser
from src.dtos.w3c_stats_dto import W3CStatsDTO
from src.dtos.user_team_season_stats_dto import UserTeamSeasonStatsDTO

class UserDTO:
    def __init__(self, data : dict):
        self.id = data.get('id')
        self.name = data.get('name')
        self.battleTag = data.get('battleTag')
        self.discordTag = data.get('discordTag')
        self.discordId = data.get('discordId')
        self.race = data.get('race')
        self.mmr = data.get('mmr')
        self.country = data.get('country')
        self.w3c_stats = data.get('w3c_stats')
        self.gnl_stats = data.get('gnl_stats')
        self.fantasy_tier = data.get('fantasy_tier')
        self.signup_seasons = data.get('signup_seasons')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'battleTag': self.battleTag,
            'discordTag': self.discordTag,
            'discordId': self.discordId,
            'race': self.race,
            'mmr': self.mmr,
            'country': self.country,
            'w3c_stats': [s.to_dict() for s in self.w3c_stats] if self.w3c_stats else [],
            'gnl_stats': [s.to_dict() for s in self.gnl_stats] if self.gnl_stats else [],
            'fantasy_tier': self.fantasy_tier,
            'signup_seasons': [s.to_dict() for s in self.signup_seasons] if self.signup_seasons else []
        }
    
    def to_db_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'battleTag': self.battleTag,
            'discordTag': self.discordTag,
            'discordId': self.discordId,
            'race': self.race,
            'mmr': self.mmr,
            'country': self.country,
            'fantasy_tier': self.fantasy_tier
        }

    @classmethod
    def from_dbuser(cls, user: DBUser):
        # import SeasonDTO lazily to avoid circular imports
        from src.dtos.season_dto import SeasonDTO

        return cls(
            {
                'id': user.id,
                'name': user.name,
                'battleTag': user.battleTag,
                'discordTag': user.discordTag,
                'discordId': user.discordId,
                'race': user.race,
                'mmr': user.mmr,
                'country': user.country,
                'w3c_stats': [W3CStatsDTO.from_dbw3cstats(s) for s in user.w3c_stats] if user.w3c_stats else [],
                'gnl_stats': [UserTeamSeasonStatsDTO.from_db_user_team_season(s) for s in user.team_seasons] if user.team_seasons else [],
                'fantasy_tier': user.fantasy_tier,
                'signup_seasons': [SeasonDTO.from_dbseason_reduced(s.season) for s in user.signup_seasons] if user.signup_seasons else []
            }
        )

    @staticmethod
    def schema():
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "User's Name"
                },
                "battleTag": {
                    "type": "string",
                    "description": "User's BattleTag"
                },
                "discordId":{
                    "type": "string",
                    "description": "User's DiscordId"
                },
                "discordTag": {
                    "type": "string",
                    "description": "User's DiscordTag"
                },
                "race": {
                    "type": "string",
                    "description": "User's Race"
                },
                "mmr": {
                    "type": "integer",
                    "description": "User's MMR"
                },
                "country": {
                    "type": "string",
                    "description": "User's Country"
                },
                "fantasy_tier": {
                    "type": "integer",
                    "description": "fantasy tier"
                }
            },
            "required": ["name", "battleTag", "discordId", "discordTag"]
        }