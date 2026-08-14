from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import DBModel
from app.models.enums import Race

if TYPE_CHECKING:
    from app.models.user import DBUser


class DBW3CStats(DBModel):
    __tablename__ = "w3cstats"
    id: Mapped[int] = mapped_column(primary_key=True)
    wc3_season: Mapped[int] = mapped_column()
    wins: Mapped[int | None] = mapped_column()
    losses: Mapped[int | None] = mapped_column()
    games: Mapped[int | None] = mapped_column()
    mmr: Mapped[int | None] = mapped_column()
    winrate: Mapped[float | None] = mapped_column()
    race: Mapped[Race | None] = mapped_column(Enum(Race))
    league: Mapped[int | None] = mapped_column()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    user: Mapped["DBUser"] = relationship(back_populates="w3c_stats")
