from src.database.model.DBMap import DBMap

class MapDTO:
    def __init__(self, data : dict):
        self.id = data.get('id')
        self.name = data.get('name')
        self.shortname = data.get('shortname')
        self.image = data.get('image')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'shortname': self.shortname,
            'image': self.image
        }
    

    @classmethod
    def from_dbmap(cls, map: DBMap):
        return cls(
                {
                'id' : map.id,
                'name' : map.name,
                'shortname' : map.shortname,
                'image' : map.image
            }
        )

    @staticmethod
    def schema():
        return {
            'type': 'object',
            'properties': {
                'name': {'type': 'string'},
                'shortname': {'type': 'string'},
                'image': {'type': 'string'}
                
            },
            'required': ['name', 'shortname']
        }