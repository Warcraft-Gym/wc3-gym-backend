from src.database.model.DBSeason import DBSeason
from src.dtos.map_dto import MapDTO

class SeasonDTO:
    def __init__(self, data : dict):
        self.id = data.get('id')
        self.name = data.get('name')
        self.number_weeks = data.get('number_weeks')
        self.series_per_week = data.get('series_per_week')
        self.pick_ban = data.get('pick_ban')
        self.maps = data.get('maps')
        self.discordRole = data.get('discordRole')
        self.user_signup = data.get('user_signup')

    def to_dict(self):

        return {
            'id': self.id,
            'name': self.name,
            'number_weeks' : self.number_weeks,
            'series_per_week': self.series_per_week,
            'pick_ban' : self.pick_ban,
            'maps' : [map.to_dict() for map in self.maps if map] if self.maps else None,
            'discordRole' : self.discordRole,
            'user_signup' : [user.to_dict() for user in self.user_signup if user] if self.user_signup else None
        }
    
    def to_db_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'number_weeks' : self.number_weeks,
            'series_per_week': self.series_per_week,
            'pick_ban' : self.pick_ban,
            'discordRole' : self.discordRole
        }

    @classmethod
    def from_dbseason(cls, season: DBSeason):
        if not season:
            return None

        return cls(
            {
                'id': season.id,
                'name': season.name,
                'number_weeks': season.number_weeks,
                'series_per_week': season.series_per_week,
                'pick_ban': season.pick_ban,
                'maps': [MapDTO.from_dbmap(map_season.map) for map_season in season.maps if map_season and map_season.map] if season.maps else [],
                'discordRole': season.discordRole,
                'user_signup': []
            }
        )
    
    @classmethod
    def from_dbseason_reduced(cls, season: DBSeason):
        if not season:
            return None

        return cls(
            {
                'id': season.id,
                'name': season.name
            }
        )
    
    @staticmethod
    def schema():
        return {
            'type': 'object',
            'properties': {
                'name': {'type': 'string'},
                'number_weeks' : {'type': 'integer'},
                'series_per_week': {'type': 'integer'},
                'pick_ban' : {'type' : 'string', 'description': 'e.g. Ban_A|Ban_B|Ban_B|Ban_A|Pick_A|Pick_B'},
                'discordRole' : {'type': 'string'}
            },
            'required': ['name','number_weeks']
        }