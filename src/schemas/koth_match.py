from typing import Annotated

from src.schemas.base import APISchema, NoneToList
from src.schemas.koth_match_participant import KothMatchParticipant


class KothMatch(APISchema):
    id: int | None = None
    event_id: int | None = None
    bracket: int | None = None
    game_mode: str | None = None
    num_teams: int | None = None
    winner_team_number: int | None = None
    participants: Annotated[list[KothMatchParticipant], NoneToList] = []

    def to_db_dict(self):
        return self.model_dump(
            include={
                "id",
                "event_id",
                "bracket",
                "game_mode",
                "num_teams",
                "winner_team_number",
            }
        )

    @classmethod
    def from_db_match(cls, match):
        if not match:
            return None

        return cls(
            id=match.id,
            event_id=match.event_id,
            bracket=match.bracket,
            game_mode=match.game_mode,
            num_teams=match.num_teams,
            winner_team_number=match.winner_team_number,
            participants=[
                KothMatchParticipant.from_db_participant(p) for p in match.participants
            ]
            if hasattr(match, "participants")
            else [],
        )
