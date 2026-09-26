from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Optional, Self

from sqlalchemy.orm.interfaces import ORMOption
from sqlmodel import Field, Relationship, SQLModel

from app.core.db import rel
from app.core.scoring import DEFAULT_WINS
from app.models.base import DBModel, ident
from app.models.match import MatchPublic
from app.models.types import AwareUTC, EnumValue, UTCDateTime
from app.models.user import UserPublic

if TYPE_CHECKING:
    from app.models.match import Match
    from app.models.user import User


class DraftSeriesBase(SQLModel):
    match_id: int = Field(index=True, foreign_key="matches.id")
    date_time: Annotated[datetime | None, AwareUTC] = Field(
        default=None, sa_type=UTCDateTime
    )
    player1_id: int = Field(index=True, foreign_key="users.id")
    player2_id: int = Field(index=True, foreign_key="users.id")
    player1_score: int | None = None
    player2_score: int | None = None
    host_player_id: int
    is_fantasy_match: bool | None = False
    # The published series this pairing replaces; the promote removes it
    replaces_series_id: int | None = Field(
        default=None, index=True, foreign_key="series.id", ondelete="CASCADE"
    )


class DraftSeries(DraftSeriesBase, DBModel, table=True):
    __tablename__ = "draft_series"

    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
    updated_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
    # Who wrote the pairing and who last changed it
    created_by_user_id: int | None = Field(
        default=None, foreign_key="users.id", ondelete="SET NULL"
    )
    updated_by_user_id: int | None = Field(
        default=None, foreign_key="users.id", ondelete="SET NULL"
    )

    match: "Match" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[DraftSeries.match_id]"}
    )
    player1: "User" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[DraftSeries.player1_id]"}
    )
    player2: "User" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[DraftSeries.player2_id]"}
    )
    # Quoting the whole union breaks the mapper, so these keep Optional["User"]
    created_by: Optional["User"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[DraftSeries.created_by_user_id]"}
    )
    updated_by: Optional["User"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[DraftSeries.updated_by_user_id]"}
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
            # A draft answer derives no ladder summary, so it reads no ladder rows
            joinedload(rel(cls.player1)).noload(rel(User.w3c_stats)),
            joinedload(rel(cls.player1)).selectinload(rel(User.team_seasons)),
            joinedload(rel(cls.player1)).selectinload(rel(User.signup_seasons)),
            joinedload(rel(cls.player2)).noload(rel(User.w3c_stats)),
            joinedload(rel(cls.player2)).selectinload(rel(User.team_seasons)),
            joinedload(rel(cls.player2)).selectinload(rel(User.signup_seasons)),
            # The two names ride the same statement; no query per row
            joinedload(rel(cls.created_by)).noload("*"),
            joinedload(rel(cls.updated_by)).noload("*"),
        )


class DraftSeriesCreate(DraftSeriesBase):
    player1_score: int | None = Field(default=None, ge=0, le=DEFAULT_WINS)  # Bo3
    player2_score: int | None = Field(default=None, ge=0, le=DEFAULT_WINS)


class DraftSeriesUpdate(SQLModel):
    match_id: int | None = None
    date_time: Annotated[datetime | None, AwareUTC] = None
    player1_id: int | None = None
    player2_id: int | None = None
    player1_score: int | None = Field(default=None, ge=0, le=DEFAULT_WINS)
    player2_score: int | None = Field(default=None, ge=0, le=DEFAULT_WINS)
    host_player_id: int | None = None
    is_fantasy_match: bool | None = None


class DraftSeriesPublic(DraftSeriesBase):
    id: int
    match_id: int | None = None
    player1_id: int | None = None
    player2_id: int | None = None
    host_player_id: int | None = None
    date_time: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    created_by_user_id: int | None = None
    created_by_name: str | None = None
    updated_by_user_id: int | None = None
    updated_by_name: str | None = None
    match: MatchPublic | None = None
    player1: UserPublic | None = None
    player2: UserPublic | None = None
    # The race each side plays, which app.services.derived resolves. A draft
    # has no result and so no off race: it is the race he signed the season up on.
    player1_race: Annotated[str | None, EnumValue] = None
    player2_race: Annotated[str | None, EnumValue] = None

    @classmethod
    def from_draft_series(cls, draft_series: DraftSeries) -> Self:
        return cls(
            id=ident(draft_series),
            match_id=draft_series.match_id,
            match=MatchPublic.from_match(draft_series.match)
            if draft_series.match
            else None,
            date_time=draft_series.date_time,
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
            replaces_series_id=draft_series.replaces_series_id,
            created_at=draft_series.created_at,
            updated_at=draft_series.updated_at,
            created_by_user_id=draft_series.created_by_user_id,
            created_by_name=draft_series.created_by.name
            if draft_series.created_by
            else None,
            updated_by_user_id=draft_series.updated_by_user_id,
            updated_by_name=draft_series.updated_by.name
            if draft_series.updated_by
            else None,
        )
