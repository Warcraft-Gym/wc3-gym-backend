from src.database.model.DBUser import DBUser
from src.dtos.w3c_stats_dto import W3CStatsDTO

class UserDTO:
    def __init__(self, data : dict):
        self.id = data.get('id')
        self.name = data.get('name')
        self.battleTag = data.get('battleTag')
        self.discordTag = data.get('discordTag')
        self.race = data.get('race')
        self.mmr = data.get('mmr')
        self.country = data.get('country')
        self.w3c_stats = data.get('w3c_stats')
        self.fantasy_tier = data.get('fantasy_tier')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'battleTag': self.battleTag,
            'discordTag': self.discordTag,
            'race': self.race,
            'mmr': self.mmr,
            'country': self.country,
            'w3c_stats': [s.to_dict() for s in self.w3c_stats] if self.w3c_stats else [],
            'fantasy_tier': self.fantasy_tier
        }

    @classmethod
    def from_dbuser(cls, user: DBUser):
        return cls(
                {
                'id': user.id,
                'name': user.name,
                'battleTag': user.battleTag,
                'discordTag': user.discordTag,
                'race': user.race,
                'mmr': user.mmr,
                'country': user.country,
                'w3c_stats': [W3CStatsDTO.from_dbw3cstats(s) for s in user.w3c_stats] if user.w3c_stats else [],
                'fantasy_tier': user.fantasy_tier
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
            "required": ["name", "battleTag", "discordTag"]
        }