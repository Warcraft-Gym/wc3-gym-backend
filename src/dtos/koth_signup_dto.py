from src.database.model.DBKothSignup import DBKothSignup

class KothSignupDTO:
    def __init__(self, data: dict):
        self.id = data.get('id')
        self.event_id = data.get('event_id')
        self.twitch_username = data.get('twitch_username')
        self.battle_tag = data.get('battle_tag')
        self.w3c_name = data.get('w3c_name')
        self.race = data.get('race')
        self.mmr = data.get('mmr')
        self.bracket = data.get('bracket')
        self.is_king = data.get('is_king')
        self.is_active = data.get('is_active', 1)

    def to_dict(self):
        return {
            'id': self.id,
            'event_id': self.event_id,
            'twitch_username': self.twitch_username,
            'battle_tag': self.battle_tag,
            'w3c_name': self.w3c_name,
            'race': self.race,
            'mmr': self.mmr,
            'bracket': self.bracket,
            'is_king': self.is_king,
            'is_active': self.is_active
        }

    def to_db_dict(self):
        return {
            'id': self.id,
            'event_id': self.event_id,
            'twitch_username': self.twitch_username,
            'battle_tag': self.battle_tag,
            'w3c_name': self.w3c_name,
            'race': self.race,
            'mmr': self.mmr,
            'bracket': self.bracket,
            'is_king': self.is_king,
            'is_active': self.is_active
        }

    @classmethod
    def from_db_signup(cls, signup: DBKothSignup):
        if not signup:
            return None
        
        return cls({
            'id': signup.id,
            'event_id': signup.event_id,
            'twitch_username': signup.twitch_username,
            'battle_tag': signup.battle_tag,
            'w3c_name': signup.w3c_name,
            'race': signup.race.value if signup.race else None,
            'mmr': signup.mmr,
            'bracket': signup.bracket,
            'is_king': signup.is_king,
            'is_active': signup.is_active
        })
