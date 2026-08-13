from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import DBModel

if TYPE_CHECKING:
    from src.models.season import DBSeason
    from src.models.series import DBSeries
    from src.models.user import DBUser


class DBFantasyBet(DBModel):
    __tablename__ = "fantasy_bets"
    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id", ondelete="CASCADE"))
    series_id: Mapped[int] = mapped_column(ForeignKey("series.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    winner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    bet_points: Mapped[int] = mapped_column()
    bet_result: Mapped[int | None] = mapped_column()

    season: Mapped["DBSeason"] = relationship(foreign_keys=[season_id])
    series: Mapped["DBSeries"] = relationship(foreign_keys=[series_id])
    user: Mapped["DBUser"] = relationship(foreign_keys=[user_id])
    winner: Mapped["DBUser"] = relationship(foreign_keys=[winner_id])

    def to_dict(self):
        return {
            column.name: getattr(self, column.name) for column in self.__table__.columns
        }
