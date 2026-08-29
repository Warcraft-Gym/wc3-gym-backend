"""The short form of a team.

It lives in its own module because three model families embed it - the
team itself, a match, and the per-season stats of a player - and it
depends on nothing, so importing it never closes a cycle.
"""

from typing import TYPE_CHECKING, Annotated, Self

from sqlmodel import SQLModel

from app.models.base import ident
from app.models.types import NumToStr

if TYPE_CHECKING:
    from app.models.team import Team


class TeamReduced(SQLModel):
    id: int
    # name and long_name also receive numeric cells from the xlsx import.
    name: Annotated[str | None, NumToStr] = None
    long_name: Annotated[str | None, NumToStr] = None
    discord_role: Annotated[str | None, NumToStr] = None

    @classmethod
    def from_team(cls, team: "Team") -> Self:
        return cls(
            id=ident(team),
            name=team.name,
            long_name=team.long_name,
            discord_role=team.discord_role,
        )
