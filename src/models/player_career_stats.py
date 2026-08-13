from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DECIMAL, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import DBModel

if TYPE_CHECKING:
    from src.models.user import DBUser


class DBPlayerCareerStats(DBModel):
    __tablename__ = "player_career_stats"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    player_name: Mapped[str] = mapped_column(String(255), unique=True)

    # Historical baseline (imported from CSV, immutable)
    historical_rating: Mapped[int | None] = mapped_column(default=0)
    historical_series_won: Mapped[int | None] = mapped_column(default=0)
    historical_series_lost: Mapped[int | None] = mapped_column(default=0)
    historical_games_won: Mapped[int | None] = mapped_column(default=0)
    historical_games_lost: Mapped[int | None] = mapped_column(default=0)
    historical_seasons_played: Mapped[int | None] = mapped_column(default=0)

    # Combined totals (historical + calculated, for display)
    rating: Mapped[int | None] = mapped_column(default=0)
    series_won: Mapped[int | None] = mapped_column(default=0)
    series_lost: Mapped[int | None] = mapped_column(default=0)
    series_winrate: Mapped[Decimal | None] = mapped_column(DECIMAL(5, 2), default=0.00)
    games_won: Mapped[int | None] = mapped_column(default=0)
    games_lost: Mapped[int | None] = mapped_column(default=0)
    games_winrate: Mapped[Decimal | None] = mapped_column(DECIMAL(5, 2), default=0.00)
    seasons_played: Mapped[int | None] = mapped_column(default=0)
    avg_series_per_season: Mapped[Decimal | None] = mapped_column(
        DECIMAL(5, 2), default=0.00
    )

    # Relationships
    user: Mapped["DBUser | None"] = relationship(back_populates="career_stats")

    def to_dict(self):
        return {
            column.name: getattr(self, column.name) for column in self.__table__.columns
        }
