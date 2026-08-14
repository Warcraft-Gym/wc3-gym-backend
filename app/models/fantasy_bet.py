from typing import TYPE_CHECKING, Annotated

from sqlmodel import Field, Relationship, SQLModel

from app.models.base import DBModel
from app.models.season import SeasonPublic
from app.models.series import SeriesPublic
from app.models.types import EmptyStrToNone
from app.models.user import UserPublic

if TYPE_CHECKING:
    from app.models.season import Season
    from app.models.series import Series
    from app.models.user import User


class FantasyBetBase(SQLModel):
    season_id: int = Field(foreign_key="seasons.id", ondelete="CASCADE")
    series_id: int = Field(foreign_key="series.id", ondelete="CASCADE")
    user_id: int = Field(foreign_key="users.id", ondelete="CASCADE")
    winner_id: int = Field(foreign_key="users.id", ondelete="CASCADE")
    bet_result: int | None = None


class FantasyBet(FantasyBetBase, DBModel, table=True):
    __tablename__ = "fantasy_bets"

    id: int | None = Field(default=None, primary_key=True)
    bet_points: int

    season: "Season" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[FantasyBet.season_id]"}
    )
    series: "Series" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[FantasyBet.series_id]"}
    )
    user: "User" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[FantasyBet.user_id]"}
    )
    winner: "User" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[FantasyBet.winner_id]"}
    )


class FantasyBetCreate(FantasyBetBase):
    # bet_points is NOT NULL, and it is still optional here: with fixed bet
    # points enabled the service fills it in from the settings, and a
    # cleared input from the UI arrives as an empty string.
    bet_points: Annotated[int | None, EmptyStrToNone] = None


class FantasyBetUpdate(SQLModel):
    season_id: int | None = None
    series_id: int | None = None
    user_id: int | None = None
    winner_id: int | None = None
    bet_points: Annotated[int | None, EmptyStrToNone] = None
    bet_result: int | None = None


class FantasyBetPublic(FantasyBetBase):
    id: int | None = None
    season_id: int | None = None
    series_id: int | None = None
    user_id: int | None = None
    winner_id: int | None = None
    bet_points: int | None = None
    season: SeasonPublic | None = None
    series: SeriesPublic | None = None
    user: UserPublic | None = None
    winner: UserPublic | None = None

    @classmethod
    def from_fantasy_bet(cls, fbet):
        if not fbet:
            return None

        return cls(
            id=fbet.id,
            series_id=fbet.series_id,
            season_id=fbet.season_id,
            season=SeasonPublic.from_season(fbet.season) if fbet.season else None,
            series=SeriesPublic.from_series(fbet.series) if fbet.series else None,
            user_id=fbet.user_id,
            user=UserPublic.from_user(fbet.user) if fbet.user else None,
            winner_id=fbet.winner_id,
            winner=UserPublic.from_user(fbet.winner) if fbet.winner else None,
            bet_points=fbet.bet_points,
            bet_result=fbet.bet_result,
        )

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")
