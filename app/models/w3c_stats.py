from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship

from app.models.base import DBModel
from app.models.enums import Race

if TYPE_CHECKING:
    from app.models.user import DBUser


class DBW3CStats(DBModel, table=True):
    __tablename__ = "w3cstats"
    id: int | None = Field(default=None, primary_key=True)
    wc3_season: int
    wins: int | None = None
    losses: int | None = None
    games: int | None = None
    mmr: int | None = None
    winrate: float | None = None
    race: Race | None = None
    league: int | None = None
    user_id: int = Field(foreign_key="users.id")
    user: "DBUser" = Relationship(back_populates="w3c_stats")
