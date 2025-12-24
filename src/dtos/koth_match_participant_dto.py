from src.database.model.DBKothMatchParticipant import DBKothMatchParticipant

class KothMatchParticipantDTO:
    def __init__(self, data: dict):
        self.id = data.get('id')
        self.match_id = data.get('match_id')
        self.signup_id = data.get('signup_id')
        self.team_number = data.get('team_number')
        self.signup = data.get('signup')  # Optional KothSignupDTO object

    def to_dict(self):
        return {
            'id': self.id,
            'match_id': self.match_id,
            'signup_id': self.signup_id,
            'team_number': self.team_number,
            'signup': self.signup.to_dict() if self.signup else None
        }

    def to_db_dict(self):
        return {
            'id': self.id,
            'match_id': self.match_id,
            'signup_id': self.signup_id,
            'team_number': self.team_number
        }

    @classmethod
    def from_db_participant(cls, participant: DBKothMatchParticipant):
        if not participant:
            return None
        
        from src.dtos.koth_signup_dto import KothSignupDTO
        
        return cls({
            'id': participant.id,
            'match_id': participant.match_id,
            'signup_id': participant.signup_id,
            'team_number': participant.team_number,
            'signup': KothSignupDTO.from_db_signup(participant.signup) if hasattr(participant, 'signup') and participant.signup else None
        })
