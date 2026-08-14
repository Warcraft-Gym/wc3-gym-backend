from datetime import datetime
from typing import Annotated

from sqlalchemy import and_, select
from sqlalchemy.orm import Session
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import DBModel
from app.models.match import Match, MatchPublic
from app.models.types import IsoDateTime, NumToStr
from app.models.user import User, UserPublic


class SeriesBase(SQLModel):
    match_id: int = Field(foreign_key="matches.id", ondelete="CASCADE")
    date_time: datetime | None = None
    caster: Annotated[str | None, NumToStr] = Field(default=None, max_length=50)
    player1_id: int = Field(foreign_key="users.id", ondelete="CASCADE")
    player2_id: int = Field(foreign_key="users.id", ondelete="CASCADE")
    player1_score: int | None = None
    player2_score: int | None = None
    player1_points: int | None = None
    player2_points: int | None = None
    host_player_id: int
    is_fantasy_match: bool | None = None


class Series(SeriesBase, DBModel, table=True):
    __tablename__ = "series"

    id: int | None = Field(default=None, primary_key=True)
    match: "Match" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Series.match_id]"}
    )
    player1: "User" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Series.player1_id]"}
    )
    player2: "User" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Series.player2_id]"}
    )

    @classmethod
    def searchForSeasonAndPlayday(cls, session: Session, season_id, playday, filters):
        stmt = select(cls).options(*cls._eager_options())
        stmt = stmt.where(
            cls.match.has(and_(Match.season_id == season_id, Match.playday == playday))
        )
        if filters is not None:
            stmt = stmt.where(filters)
        return session.scalars(stmt).unique().all()

    @classmethod
    def searchForSeason(cls, session: Session, season_id, filters):
        stmt = select(cls).options(*cls._eager_options())
        stmt = stmt.where(cls.match.has(Match.season_id == season_id))
        if filters is not None:
            stmt = stmt.where(filters)
        return session.scalars(stmt).unique().all()

    @classmethod
    def _eager_options(cls):
        """The rows a season report reads off every series."""
        from sqlalchemy.orm import joinedload

        from app.models.relationships import DBUserTeamSeason

        return (
            joinedload(cls.match).joinedload(Match.team1),
            joinedload(cls.match).joinedload(Match.team2),
            joinedload(cls.player1).joinedload(User.w3c_stats),
            joinedload(cls.player1)
            .joinedload(User.team_seasons)
            .joinedload(DBUserTeamSeason.season),
            joinedload(cls.player2).joinedload(User.w3c_stats),
            joinedload(cls.player2)
            .joinedload(User.team_seasons)
            .joinedload(DBUserTeamSeason.season),
        )


class SeriesCreate(SeriesBase):
    pass


class SeriesUpdate(SQLModel):
    match_id: int | None = None
    date_time: datetime | None = None
    caster: Annotated[str | None, NumToStr] = None
    player1_id: int | None = None
    player2_id: int | None = None
    player1_score: int | None = None
    player2_score: int | None = None
    player1_points: int | None = None
    player2_points: int | None = None
    host_player_id: int | None = None
    is_fantasy_match: bool | None = None


class SeriesPublic(SeriesBase):
    id: int | None = None
    match_id: int | None = None
    player1_id: int | None = None
    player2_id: int | None = None
    host_player_id: int | None = None
    date_time: IsoDateTime | None = None
    match: MatchPublic | None = None
    player1: UserPublic | None = None
    player2: UserPublic | None = None

    @classmethod
    def from_series(cls, series):
        if not series:
            return None

        return cls(
            id=series.id,
            match_id=series.match_id,
            match=MatchPublic.from_match(series.match) if series.match else None,
            date_time=series.date_time,
            caster=series.caster,
            player1_id=series.player1_id,
            player1=UserPublic.from_user(series.player1) if series.player1 else None,
            player2_id=series.player2_id,
            player2=UserPublic.from_user(series.player2) if series.player2 else None,
            player1_score=series.player1_score,
            player2_score=series.player2_score,
            player1_points=series.player1_points,
            player2_points=series.player2_points,
            host_player_id=series.host_player_id,
            is_fantasy_match=series.is_fantasy_match,
        )

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")
