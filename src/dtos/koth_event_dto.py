from src.database.model.DBKothEvent import DBKothEvent

class KothEventDTO:
    def __init__(self, data: dict):
        self.id = data.get('id')
        self.name = data.get('name')
        self.description = data.get('description')
        self.event_date = data.get('event_date')
        self.is_active = data.get('is_active')
        self.bracket_1_threshold = data.get('bracket_1_threshold')
        self.bracket_2_threshold = data.get('bracket_2_threshold')
        self.signups = data.get('signups', [])
        self.matches = data.get('matches', [])

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'event_date': self.event_date.isoformat() if self.event_date else None,
            'is_active': self.is_active,
            'bracket_1_threshold': self.bracket_1_threshold,
            'bracket_2_threshold': self.bracket_2_threshold,
            'signups': [s.to_dict() for s in self.signups if s] if self.signups else [],
            'matches': [m.to_dict() for m in self.matches if m] if self.matches else []
        }

    def to_db_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'event_date': self.event_date,
            'is_active': self.is_active,
            'bracket_1_threshold': self.bracket_1_threshold,
            'bracket_2_threshold': self.bracket_2_threshold
        }

    @classmethod
    def from_db_event(cls, event: DBKothEvent):
        if not event:
            return None
        from src.dtos.koth_signup_dto import KothSignupDTO
        from src.dtos.koth_match_dto import KothMatchDTO
        
        return cls({
            'id': event.id,
            'name': event.name,
            'description': event.description,
            'event_date': event.event_date,
            'is_active': event.is_active,
            'bracket_1_threshold': event.bracket_1_threshold,
            'bracket_2_threshold': event.bracket_2_threshold,
            'signups': [KothSignupDTO.from_db_signup(s) for s in event.signups] if hasattr(event, 'signups') else [],
            'matches': [KothMatchDTO.from_db_match(m) for m in event.matches] if hasattr(event, 'matches') else []
        })
