from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import and_, select
from sqlalchemy.orm import Session
from sqlmodel import Field, Relationship

from app.models.base import DBModel
from app.models.match import DBMatch

if TYPE_CHECKING:
    from app.models.user import DBUser


class DBSeries(DBModel, table=True):
    __tablename__ = "series"
    id: int | None = Field(default=None, primary_key=True)
    match_id: int = Field(foreign_key="matches.id", ondelete="CASCADE")
    date_time: datetime | None = None
    caster: str | None = Field(default=None, max_length=50)
    player1_id: int = Field(foreign_key="users.id", ondelete="CASCADE")
    player2_id: int = Field(foreign_key="users.id", ondelete="CASCADE")
    player1_score: int | None = None
    player2_score: int | None = None
    player1_points: int | None = None
    player2_points: int | None = None
    host_player_id: int
    is_fantasy_match: bool | None = None

    match: "DBMatch" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[DBSeries.match_id]"}
    )
    player1: "DBUser" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[DBSeries.player1_id]"}
    )
    player2: "DBUser" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[DBSeries.player2_id]"}
    )

    def to_dict(self):
        return {
            column.name: getattr(self, column.name) for column in self.__table__.columns
        }

    @classmethod
    def searchForSeasonAndPlayday(cls, session: Session, season_id, playday, filters):
        from sqlalchemy.orm import joinedload

        from app.models.relationships import DBUserTeamSeason
        from app.models.user import DBUser

        stmt = select(cls).options(
            joinedload(cls.match).joinedload(DBMatch.team1),
            joinedload(cls.match).joinedload(DBMatch.team2),
            joinedload(cls.player1).joinedload(DBUser.w3c_stats),
            joinedload(cls.player1)
            .joinedload(DBUser.team_seasons)
            .joinedload(DBUserTeamSeason.season),
            joinedload(cls.player2).joinedload(DBUser.w3c_stats),
            joinedload(cls.player2)
            .joinedload(DBUser.team_seasons)
            .joinedload(DBUserTeamSeason.season),
        )

        stmt = stmt.where(
            cls.match.has(
                and_(DBMatch.season_id == season_id, DBMatch.playday == playday)
            )
        )
        if filters is not None:
            stmt = stmt.where(filters)
        return session.scalars(stmt).unique().all()

    @classmethod
    def searchForSeason(cls, session: Session, season_id, filters):
        from sqlalchemy.orm import joinedload

        from app.models.relationships import DBUserTeamSeason
        from app.models.user import DBUser

        stmt = select(cls).options(
            joinedload(cls.match).joinedload(DBMatch.team1),
            joinedload(cls.match).joinedload(DBMatch.team2),
            joinedload(cls.player1).joinedload(DBUser.w3c_stats),
            joinedload(cls.player1)
            .joinedload(DBUser.team_seasons)
            .joinedload(DBUserTeamSeason.season),
            joinedload(cls.player2).joinedload(DBUser.w3c_stats),
            joinedload(cls.player2)
            .joinedload(DBUser.team_seasons)
            .joinedload(DBUserTeamSeason.season),
        )

        stmt = stmt.where(cls.match.has(DBMatch.season_id == season_id))
        if filters is not None:
            stmt = stmt.where(filters)
        return session.scalars(stmt).unique().all()
