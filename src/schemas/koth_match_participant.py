from src.schemas.base import APISchema
from src.schemas.koth_signup import KothSignup


class KothMatchParticipant(APISchema):
    id: int | None = None
    match_id: int | None = None
    signup_id: int | None = None
    team_number: int | None = None
    signup: KothSignup | None = None

    def to_db_dict(self):
        return self.model_dump(include={'id', 'match_id', 'signup_id', 'team_number'})

    @classmethod
    def from_db_participant(cls, participant):
        if not participant:
            return None

        return cls(
            id=participant.id,
            match_id=participant.match_id,
            signup_id=participant.signup_id,
            team_number=participant.team_number,
            signup=KothSignup.from_db_signup(participant.signup) if hasattr(participant, 'signup') and participant.signup else None,
        )
