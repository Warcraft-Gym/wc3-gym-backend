from typing import Annotated

from src.schemas.base import APISchema, EnumValue


class KothSignup(APISchema):
    id: int | None = None
    event_id: int | None = None
    twitch_username: str | None = None
    battle_tag: str | None = None
    w3c_name: str | None = None
    race: Annotated[str | None, EnumValue] = None
    mmr: int | None = None
    bracket: int | None = None
    is_king: int | None = None
    is_active: int | None = 1

    def to_db_dict(self):
        return self.model_dump()

    @classmethod
    def from_db_signup(cls, signup):
        if not signup:
            return None

        return cls(
            id=signup.id,
            event_id=signup.event_id,
            twitch_username=signup.twitch_username,
            battle_tag=signup.battle_tag,
            w3c_name=signup.w3c_name,
            race=signup.race,
            mmr=signup.mmr,
            bracket=signup.bracket,
            is_king=signup.is_king,
            is_active=signup.is_active,
        )
