from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DECIMAL
from sqlmodel import Field, Relationship

from app.models.base import DBModel

if TYPE_CHECKING:
    from app.models.user import DBUser


class DBPlayerCareerStats(DBModel, table=True):
    __tablename__ = "player_career_stats"

    id: int | None = Field(
        default=None, primary_key=True, sa_column_kwargs={"autoincrement": True}
    )
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
    series_winrate: Decimal | None = Field(default=0.00, sa_type=DECIMAL(5, 2))
    games_won: int | None = 0
    games_lost: int | None = 0
    games_winrate: Decimal | None = Field(default=0.00, sa_type=DECIMAL(5, 2))
    seasons_played: int | None = 0
    avg_series_per_season: Decimal | None = Field(default=0.00, sa_type=DECIMAL(5, 2))

    # Relationships
    user: Optional["DBUser"] = Relationship(back_populates="career_stats")

    def to_dict(self):
        return {
            column.name: getattr(self, column.name) for column in self.__table__.columns
        }
