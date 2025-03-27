from src.database.model.DBSeason import DBSeason
from src.database.model.DBMap import DBMap
from src.dtos.map_dto import MapDTO

class SeasonDTO:
    def __init__(self, data : dict):
        self.id = data.get('id')
        self.name = data.get('name')
        self.number_weeks = data.get('number_weeks')
        self.pick_ban = data.get('pick_ban')
        self.maps = data.get('maps')

    def to_dict(self):

        return {
            'id': self.id,
            'name': self.name,
            'number_weeks' : self.number_weeks,
            'pick_ban' : self.pick_ban,
            'maps' : [map.to_dict() for map in self.maps] if self.maps else None
        }
    
    def to_db_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'number_weeks' : self.number_weeks,
            'pick_ban' : self.pick_ban
        }

    @classmethod
    def from_dbseason(cls, season: DBSeason):
        if not season:
            return None

        return cls(
                {
                'id' : season.id,
                'name' : season.name,
                'number_weeks' : season.number_weeks,
                'pick_ban' : season.pick_ban,
                'maps' : [MapDTO.from_dbmap(map_season.map) for map_season in season.maps ]
            }
        )
    
    @staticmethod
    def schema():
        return {
            'type': 'object',
            'properties': {
                'name': {'type': 'string'},
                'number_weeks' : {'type': 'integer'},
                'pick_ban' : {'type' : 'string', 'description': 'e.g. Ban_A|Ban_B|Ban_B|Ban_A|Pick_A|Pick_B'}
            },
            'required': ['name','number_weeks']
        }