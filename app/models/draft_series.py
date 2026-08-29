from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Self

from sqlalchemy import TIMESTAMP
from sqlalchemy.orm.interfaces import ORMOption
from sqlmodel import Field, Relationship, SQLModel

from app.core.db import rel
from app.models.base import DBModel, ident
from app.models.match import MatchPublic
from app.models.types import IsoDateTime, NumToStr
from app.models.user import UserPublic

if TYPE_CHECKING:
    from app.models.match import Match
    from app.models.user import User


class DraftSeriesBase(SQLModel):
    match_id: int = Field(index=True, foreign_key="matches.id")
    date_time: datetime | None = None
    caster: Annotated[str | None, NumToStr] = Field(default=None, max_length=50)
    player1_id: int = Field(index=True, foreign_key="users.id")
    player2_id: int = Field(index=True, foreign_key="users.id")
    player1_score: int | None = 0
    player2_score: int | None = 0
    host_player_id: int
    is_fantasy_match: bool | None = False


class DraftSeries(DraftSeriesBase, DBModel, table=True):
    __tablename__ = "draft_series"

    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime | None = Field(default=None, sa_type=TIMESTAMP)

    match: "Match" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[DraftSeries.match_id]"}
    )
    player1: "User" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[DraftSeries.player1_id]"}
    )
    player2: "User" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[DraftSeries.player2_id]"}
    )

    @classmethod
    def _eager_options(cls) -> tuple[ORMOption, ...]:
        """The rows a match draft reads off every draft series."""
        from sqlalchemy.orm import joinedload

        from app.models.match import Match
        from app.models.user import User

        return (
            joinedload(rel(cls.match)).joinedload(rel(Match.team1)),
            joinedload(rel(cls.match)).joinedload(rel(Match.team2)),
            joinedload(rel(cls.match)).joinedload(rel(Match.season)),
            joinedload(rel(cls.player1)).selectinload(rel(User.w3c_stats)),
            joinedload(rel(cls.player1)).selectinload(rel(User.team_seasons)),
            joinedload(rel(cls.player1)).selectinload(rel(User.signup_seasons)),
            joinedload(rel(cls.player2)).selectinload(rel(User.w3c_stats)),
            joinedload(rel(cls.player2)).selectinload(rel(User.team_seasons)),
            joinedload(rel(cls.player2)).selectinload(rel(User.signup_seasons)),
        )


class DraftSeriesCreate(DraftSeriesBase):
    pass


class DraftSeriesUpdate(SQLModel):
    match_id: int | None = None
    date_time: datetime | None = None
    caster: Annotated[str | None, NumToStr] = None
    player1_id: int | None = None
    player2_id: int | None = None
    player1_score: int | None = None
    player2_score: int | None = None
    host_player_id: int | None = None
    is_fantasy_match: bool | None = None


class DraftSeriesPublic(DraftSeriesBase):
    id: int
    match_id: int | None = None
    player1_id: int | None = None
    player2_id: int | None = None
    host_player_id: int | None = None
    date_time: IsoDateTime | None = None
    created_at: IsoDateTime | None = None
    match: MatchPublic | None = None
    player1: UserPublic | None = None
    player2: UserPublic | None = None

    @classmethod
    def from_draft_series(cls, draft_series: DraftSeries) -> Self:
        return cls(
            id=ident(draft_series),
            match_id=draft_series.match_id,
            match=MatchPublic.from_match(draft_series.match)
            if draft_series.match
            else None,
            date_time=draft_series.date_time,
            caster=draft_series.caster,
            player1_id=draft_series.player1_id,
            player1=UserPublic.from_user(draft_series.player1)
            if draft_series.player1
            else None,
            player2_id=draft_series.player2_id,
            player2=UserPublic.from_user(draft_series.player2)
            if draft_series.player2
            else None,
            player1_score=draft_series.player1_score,
            player2_score=draft_series.player2_score,
            host_player_id=draft_series.host_player_id,
            is_fantasy_match=draft_series.is_fantasy_match,
            created_at=draft_series.created_at,
        )
