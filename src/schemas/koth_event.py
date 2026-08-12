from typing import Annotated

from src.schemas.base import APISchema, IsoDateTime, NoneToList
from src.schemas.koth_match import KothMatch
from src.schemas.koth_signup import KothSignup


class KothEvent(APISchema):
    id: int | None = None
    name: str | None = None
    description: str | None = None
    event_date: IsoDateTime | None = None
    is_active: bool | None = None
    bracket_1_threshold: int | None = None
    bracket_2_threshold: int | None = None
    signups: Annotated[list[KothSignup], NoneToList] = []
    matches: Annotated[list[KothMatch], NoneToList] = []

    def to_db_dict(self):
        return self.model_dump(
            include={
                'id', 'name', 'description', 'event_date', 'is_active',
                'bracket_1_threshold', 'bracket_2_threshold',
            }
        )

    @classmethod
    def from_db_event(cls, event):
        if not event:
            return None

        return cls(
            id=event.id,
            name=event.name,
            description=event.description,
            event_date=event.event_date,
            is_active=event.is_active,
            bracket_1_threshold=event.bracket_1_threshold,
            bracket_2_threshold=event.bracket_2_threshold,
            signups=[KothSignup.from_db_signup(s) for s in event.signups] if hasattr(event, 'signups') else [],
            matches=[KothMatch.from_db_match(m) for m in event.matches] if hasattr(event, 'matches') else [],
        )
