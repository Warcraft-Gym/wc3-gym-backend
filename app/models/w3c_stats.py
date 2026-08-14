from typing import TYPE_CHECKING, Annotated, Any

from sqlmodel import Field, Relationship, SQLModel

from app.models.base import DBModel
from app.models.enums import Race
from app.models.types import RoundToInt

if TYPE_CHECKING:
    from app.models.user import User


class W3CStatsBase(SQLModel):
    # The w3champions API can send fractional numbers for these columns.
    wc3_season: Annotated[int, RoundToInt]
    wins: Annotated[int | None, RoundToInt] = None
    losses: Annotated[int | None, RoundToInt] = None
    games: Annotated[int | None, RoundToInt] = None
    mmr: Annotated[int | None, RoundToInt] = None
    winrate: float | None = None
    league: Annotated[int | None, RoundToInt] = None


class W3CStats(W3CStatsBase, DBModel, table=True):
    __tablename__ = "w3cstats"

    id: int | None = Field(default=None, primary_key=True)
    race: Race | None = None
    user_id: int = Field(foreign_key="users.id")
    user: "User" = Relationship(back_populates="w3c_stats")


class W3CStatsCreate(W3CStatsBase):
    # A Race member when the value comes from the w3champions sync, a plain
    # string when it comes from request JSON. Services compare members, so
    # the value is not coerced.
    race: Race | str | None = None
    # user_id is not here: the caller of the sync owns which user the row
    # belongs to, so the service supplies it.


class W3CStatsPublic(W3CStatsBase):
    id: int
    race: Race | str | None = None
    user_id: int

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
