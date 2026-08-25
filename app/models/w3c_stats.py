from typing import TYPE_CHECKING, Annotated, Any

from sqlalchemy import Index
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import DBModel
from app.models.enums import Race
from app.models.types import EnumValue, RoundToInt, SuggestRace

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
    # The w3champions API sends one record per race per season
    __table_args__ = (
        Index(
            "uq_w3cstats_user_id_race_wc3_season",
            "user_id",
            "race",
            "wc3_season",
            unique=True,
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    race: Race | None = None
    user_id: int = Field(foreign_key="users.id")
    user: "User" = Relationship(back_populates="w3c_stats")


class W3CStatsCreate(W3CStatsBase):
    race: Annotated[Race | None, SuggestRace] = None
    # user_id is not here: the sync service supplies it


class W3CStatsPublic(W3CStatsBase):
    id: int
    race: Annotated[str | None, EnumValue] = None
    user_id: int

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class W3CSyncFailure(SQLModel):
    """One player the sync could not update, and the reason it gives the admin."""

    id: int
    name: str | None = None
    battleTag: str | None = None
    reason: str


class W3CSyncResult(SQLModel):
    """What one sync did, player by player."""

    synced: list[int] = Field(default_factory=list)
    skipped: list[int] = Field(default_factory=list)
    failed: list[W3CSyncFailure] = Field(default_factory=list)
