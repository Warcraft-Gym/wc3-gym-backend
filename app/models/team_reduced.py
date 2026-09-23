"""The short form of a team.

It lives in its own module because three model families embed it - the
team itself, a match, and the per-season stats of a player - and it
depends on nothing, so importing it never closes a cycle.
"""

from typing import TYPE_CHECKING, Self

from sqlmodel import SQLModel

from app.models.base import ident

if TYPE_CHECKING:
    from app.models.team import Team


class TeamReduced(SQLModel):
    id: int
    league_id: int
    # name and long_name also receive numeric cells from the xlsx import.
    name: str | None = None
    long_name: str | None = None
    # where the logo is served from; None until one is uploaded
    icon_url: str | None = None

    @classmethod
    def from_team(cls, team: "Team") -> Self:
        return cls(
            id=ident(team),
            league_id=team.league_id,
            name=team.name,
            long_name=team.long_name,
            icon_url=team.icon_url,
        )
