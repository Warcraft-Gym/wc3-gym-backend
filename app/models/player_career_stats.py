from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DECIMAL
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import DBModel
from app.models.user import UserPublic

if TYPE_CHECKING:
    from app.models.user import User

# The response reads these as floats, and null or zero reads as 0.0.
_FLOAT_FIELDS = ("series_winrate", "games_winrate", "avg_series_per_season")


class PlayerCareerStatsBase(SQLModel):
    user_id: int | None = Field(
        default=None, foreign_key="users.id", ondelete="SET NULL"
    )
    player_name: str = Field(max_length=255, unique=True)

    # Historical baseline (imported from CSV, immutable)
    historical_rating: int | None = 0
    historical_series_won: int | None = 0
    historical_series_lost: int | None = 0
    historical_games_won: int | None = 0
    historical_games_lost: int | None = 0
    historical_seasons_played: int | None = 0

    # Combined totals (historical + calculated, for display)
    rating: int | None = 0
    series_won: int | None = 0
    series_lost: int | None = 0
    games_won: int | None = 0
    games_lost: int | None = 0
    seasons_played: int | None = 0


class PlayerCareerStats(PlayerCareerStatsBase, DBModel, table=True):
    __tablename__ = "player_career_stats"

    id: int | None = Field(
        default=None, primary_key=True, sa_column_kwargs={"autoincrement": True}
    )
    series_winrate: Decimal | None = Field(default=0.00, sa_type=DECIMAL(5, 2))
    games_winrate: Decimal | None = Field(default=0.00, sa_type=DECIMAL(5, 2))
    avg_series_per_season: Decimal | None = Field(default=0.00, sa_type=DECIMAL(5, 2))

    # Relationships
    user: Optional["User"] = Relationship(back_populates="career_stats")


class PlayerCareerStatsCreate(PlayerCareerStatsBase):
    series_winrate: float | None = None
    games_winrate: float | None = None
    avg_series_per_season: float | None = None


class PlayerCareerStatsUpdate(SQLModel):
    user_id: int | None = None
    player_name: str | None = None
    historical_rating: int | None = None
    historical_series_won: int | None = None
    historical_series_lost: int | None = None
    historical_games_won: int | None = None
    historical_games_lost: int | None = None
    historical_seasons_played: int | None = None
    rating: int | None = None
    series_won: int | None = None
    series_lost: int | None = None
    series_winrate: float | None = None
    games_won: int | None = None
    games_lost: int | None = None
    games_winrate: float | None = None
    seasons_played: int | None = None
    avg_series_per_season: float | None = None


class PlayerCareerStatsPublic(PlayerCareerStatsBase):
    id: int | None = None
    player_name: str | None = None
    user: UserPublic | None = None
    series_winrate: float | None = None
    games_winrate: float | None = None
    avg_series_per_season: float | None = None

    @classmethod
    def from_career_stats(cls, stats):
        if not stats:
            return None

        return cls(
            id=stats.id,
            user_id=stats.user_id,
            player_name=stats.player_name,
            user=UserPublic.from_user(stats.user) if stats.user else None,
            historical_rating=stats.historical_rating,
            historical_series_won=stats.historical_series_won,
            historical_series_lost=stats.historical_series_lost,
            historical_games_won=stats.historical_games_won,
            historical_games_lost=stats.historical_games_lost,
            historical_seasons_played=stats.historical_seasons_played,
            rating=stats.rating,
            series_won=stats.series_won,
            series_lost=stats.series_lost,
            series_winrate=stats.series_winrate,
            games_won=stats.games_won,
            games_lost=stats.games_lost,
            games_winrate=stats.games_winrate,
            seasons_played=stats.seasons_played,
            avg_series_per_season=stats.avg_series_per_season,
        )

    def to_dict(self) -> dict:
        result = self.model_dump(mode="json")
        for key in _FLOAT_FIELDS:
            result[key] = result[key] if result[key] else 0.0
        return result
