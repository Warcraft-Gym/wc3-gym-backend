from src.database.model.DBUser import DBUser
class UserDTO:
    def __init__(self, data : dict):
        self.id = data.get('id')
        self.name = data.get('name')
        self.battleTag = data.get('battleTag')
        self.discordTag = data.get('discordTag')
        self.race = data.get('race')
        self.mmr = data.get('mmr')
        self.country = data.get('country')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'battleTag': self.battleTag,
            'discordTag': self.discordTag,
            'race': self.race,
            'mmr': self.mmr,
            'country': self.country
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
                'country': user.country
            }
        )
