from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import TIMESTAMP
from sqlmodel import Field, Relationship

from app.models.base import DBModel

if TYPE_CHECKING:
    from app.models.match import Match
    from app.models.user import User


class DBDraftSeries(DBModel, table=True):
    __tablename__ = "draft_series"
    id: int | None = Field(default=None, primary_key=True)
    match_id: int = Field(foreign_key="matches.id")
    date_time: datetime | None = None
    caster: str | None = Field(default=None, max_length=50)
    player1_id: int = Field(foreign_key="users.id")
    player2_id: int = Field(foreign_key="users.id")
    player1_score: int | None = 0
    player2_score: int | None = 0
    host_player_id: int
    is_fantasy_match: bool | None = False
    created_at: datetime | None = Field(default=None, sa_type=TIMESTAMP)

    match: "Match" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[DBDraftSeries.match_id]"}
    )
    player1: "User" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[DBDraftSeries.player1_id]"}
    )
    player2: "User" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[DBDraftSeries.player2_id]"}
    )

    def to_dict(self):
        return {
            column.name: getattr(self, column.name) for column in self.__table__.columns
        }
