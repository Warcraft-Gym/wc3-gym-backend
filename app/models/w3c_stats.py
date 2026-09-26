from typing import TYPE_CHECKING, Annotated

from sqlalchemy import Index
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import DBModel
from app.models.enums import Race
from app.models.types import EnumValue, RoundToInt, SuggestRace

if TYPE_CHECKING:
    from app.models.user import User


class W3CStatsBase(SQLModel):
    wc3_season: int
    wins: int | None = None
    losses: int | None = None
    games: int | None = None
    mmr: int | None = None
    winrate: float | None = None
    league: int | None = None


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
    # The w3champions API can send fractional numbers for these columns.
    wc3_season: Annotated[int, RoundToInt]
    wins: Annotated[int | None, RoundToInt] = None
    losses: Annotated[int | None, RoundToInt] = None
    games: Annotated[int | None, RoundToInt] = None
    mmr: Annotated[int | None, RoundToInt] = None
    league: Annotated[int | None, RoundToInt] = None
    race: Annotated[Race | None, SuggestRace] = None
    # user_id is not here: the sync service supplies it


class W3CStatsPublic(W3CStatsBase):
    id: int
    race: Annotated[str | None, EnumValue] = None
    user_id: int


class RaceMmr(SQLModel):
    """One race of a player's ladder summary: the newest window row's rating, the window's games."""

    race: str | None
    wc3_season: int  # the season the mmr comes from
    mmr: int | None
    games: int | None  # summed over the window rows of this race
    wins: int | None
    losses: int | None
    # true when the row is older than the window (profile reads only)
    stale: bool = False


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
