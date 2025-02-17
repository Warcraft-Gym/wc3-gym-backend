from src.database.model.DBSeason import DBSeason

class SeasonDTO:
    def __init__(self, data : dict):
        self.id = data.get('id')
        self.name = data.get('name')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name
        }

    @classmethod
    def from_dbseason(cls, season: DBSeason):
        return cls(
                {
                'id' : season.id,
                'name' : season.name
            }
        )
