from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import DBModel

if TYPE_CHECKING:
    from app.models.map import DBMap
    from app.models.season import DBSeason
    from app.models.team import DBTeam


class DBMatch(DBModel):
    __tablename__ = "matches"
    id: Mapped[int] = mapped_column(primary_key=True)
    team1_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    team2_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id", ondelete="CASCADE"))
    playday: Mapped[int] = mapped_column()
    team1_score: Mapped[int | None] = mapped_column()
    team2_score: Mapped[int | None] = mapped_column()
    fixed_map_id: Mapped[int | None] = mapped_column(ForeignKey("maps.id"))
    date_frame: Mapped[str | None] = mapped_column(String(50))

    team1: Mapped["DBTeam"] = relationship(foreign_keys=[team1_id])
    team2: Mapped["DBTeam"] = relationship(foreign_keys=[team2_id])
    season: Mapped["DBSeason"] = relationship(foreign_keys=[season_id])
    fixed_map: Mapped["DBMap | None"] = relationship(foreign_keys=[fixed_map_id])

    def to_dict(self):
        return {
            column.name: getattr(self, column.name) for column in self.__table__.columns
        }
