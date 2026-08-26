from typing import Any, Self

from sqlalchemy.orm import joinedload
from sqlalchemy.sql.base import ExecutableOption
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import DBModel
from app.models.user import User, UserReduced

# The response reads these as floats, and null or zero reads as 0.0.
_FLOAT_FIELDS = ("series_winrate", "games_winrate", "avg_series_per_season")


class PlayerCareerStatsBase(SQLModel):
    user_id: int | None = Field(
        index=True, default=None, foreign_key="users.id", ondelete="SET NULL"
    )
    player_name: str = Field(max_length=255, unique=True)

    # Historical baseline (imported from CSV, immutable)
    historical_rating: int | None = 0
    historical_series_won: int | None = 0
    historical_series_lost: int | None = 0
    historical_games_won: int | None = 0
    historical_games_lost: int | None = 0
    historical_seasons_played: int | None = 0


class PlayerCareerStats(PlayerCareerStatsBase, DBModel, table=True):
    __tablename__ = "player_career_stats"

    id: int | None = Field(
        default=None, primary_key=True, sa_column_kwargs={"autoincrement": True}
    )

    # Relationships
    user: User | None = Relationship(back_populates="career_stats")

    @classmethod
    def eager_options(cls) -> tuple[ExecutableOption, ...]:
        """Every relation the public career row reads."""
        return (joinedload(cls.user),)


class PlayerCareerStatsUpdate(SQLModel):
    user_id: int | None = None
    player_name: str | None = None
    historical_rating: int | None = None
    historical_series_won: int | None = None
    historical_series_lost: int | None = None
    historical_games_won: int | None = None
    historical_games_lost: int | None = None
    historical_seasons_played: int | None = None


class PlayerCareerStatsPublic(PlayerCareerStatsBase):
    # app.services.derived.fill_career answers these nine; no column holds them
    rating: int | None = 0
    series_won: int | None = 0
    series_lost: int | None = 0
    games_won: int | None = 0
    games_lost: int | None = 0
    seasons_played: int | None = 0
    id: int | None = None
    player_name: str | None = None
    # The career table reads the name and the id, so the collections stay out
    user: UserReduced | None = None
    series_winrate: float | None = None
    games_winrate: float | None = None
    avg_series_per_season: float | None = None

    @classmethod
    def from_career_stats(cls, stats: PlayerCareerStats | None) -> Self | None:
        if not stats:
            return None

        return cls(
            id=stats.id,
            user_id=stats.user_id,
            player_name=stats.player_name,
            user=UserReduced.from_user_reduced(stats.user),
            historical_rating=stats.historical_rating,
            historical_series_won=stats.historical_series_won,
            historical_series_lost=stats.historical_series_lost,
            historical_games_won=stats.historical_games_won,
            historical_games_lost=stats.historical_games_lost,
            historical_seasons_played=stats.historical_seasons_played,
        )

    def to_dict(self) -> dict[str, Any]:
        result = self.model_dump(mode="json")
        for key in _FLOAT_FIELDS:
            result[key] = result[key] if result[key] else 0.0
        return result
