from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Any, Literal, Self

from sqlalchemy import ColumnElement, ColumnExpressionArgument, Index, and_, select
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy.orm.interfaces import ORMOption
from sqlmodel import Field, Relationship, SQLModel, col

from app.core.db import rel
from app.core.ordering import SortOrder, ordered
from app.models.base import DBModel, PublicModel, ident
from app.models.enums import Race
from app.models.match import Match, MatchPublic
from app.models.series_cast import CastPublic, SeriesCast
from app.models.series_veto_step import DBSeriesVetoStep
from app.models.types import AwareUTC, EnumValue, SuggestRace, UTCDateTime
from app.models.user import User, UserPublic

SeriesSort = Literal["date_time", "week", "id"]


class SeriesBase(SQLModel):
    match_id: int = Field(index=True, foreign_key="matches.id", ondelete="CASCADE")
    date_time: Annotated[datetime | None, AwareUTC] = Field(
        default=None, sa_type=UTCDateTime
    )
    player1_id: int = Field(index=True, foreign_key="users.id", ondelete="CASCADE")
    player2_id: int = Field(index=True, foreign_key="users.id", ondelete="CASCADE")
    player1_score: int | None = None
    player2_score: int | None = None
    host_player_id: int
    is_fantasy_match: bool | None = None
    # The race a side played when it is not the one he signed the season up on
    player1_off_race: Annotated[Race | None, SuggestRace] = None
    player2_off_race: Annotated[Race | None, SuggestRace] = None


class Series(SeriesBase, DBModel, table=True):
    __tablename__ = "series"
    # A pair of players meet once inside a team series
    __table_args__ = (
        Index(
            "uq_series_match_id_player1_id_player2_id",
            "match_id",
            "player1_id",
            "player2_id",
            unique=True,
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    # The round this series is played in; backfilled in C1, required from C2.
    # It stays off SeriesBase, so the series payloads are unchanged.
    round_id: int | None = Field(
        default=None, index=True, foreign_key="event_round.id", ondelete="CASCADE"
    )
    match: "Match" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Series.match_id]"}
    )
    player1: "User" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Series.player1_id]"}
    )
    player2: "User" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Series.player2_id]"}
    )
    casts: list[SeriesCast] = Relationship(
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    veto_steps: list[DBSeriesVetoStep] = Relationship(
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )

    @classmethod
    def search_for_season_and_playday(
        cls,
        session: Session,
        season_id: int,
        playday: int,
        filters: ColumnExpressionArgument[bool] | None,
        limit: int | None = None,
        offset: int = 0,
    ) -> Sequence[Self]:
        stmt = select(cls).options(*cls._list_eager_options())
        stmt = stmt.where(
            col(cls.match).has(
                and_(col(Match.season_id) == season_id, col(Match.playday) == playday)
            )
        )
        if filters is not None:
            stmt = stmt.where(filters)
        # Offset paging is deterministic only with a fixed order
        stmt = stmt.order_by(col(cls.id)).offset(offset).limit(limit)
        return session.scalars(stmt).all()

    @classmethod
    def search_for_season(
        cls,
        session: Session,
        season_id: int,
        filters: ColumnExpressionArgument[bool] | None,
        limit: int | None = None,
        offset: int = 0,
        *,
        sort: SeriesSort | None = None,
        order: SortOrder = "asc",
    ) -> Sequence[Self]:
        stmt = select(cls).options(*cls._list_eager_options())
        stmt = stmt.where(col(cls.match).has(col(Match.season_id) == season_id))
        if filters is not None:
            stmt = stmt.where(filters)
        if sort == "week":
            stmt = stmt.join(Match, col(Match.id) == cls.match_id)
        # Offset paging is deterministic only with a fixed order
        stmt = (
            ordered(stmt, SERIES_SORTS, sort, order, col(cls.id))
            .offset(offset)
            .limit(limit)
        )
        return session.scalars(stmt).all()

    @classmethod
    def _list_eager_options(cls) -> tuple[ORMOption, ...]:
        """The to-one relations the reduced public series reads."""
        return (
            joinedload(rel(cls.match)).joinedload(rel(Match.team1)),
            joinedload(rel(cls.match)).joinedload(rel(Match.team2)),
            joinedload(rel(cls.match)).joinedload(rel(Match.season)),
            joinedload(rel(cls.match)).joinedload(rel(Match.fixed_map)),
            joinedload(rel(cls.player1)),
            joinedload(rel(cls.player2)),
            selectinload(rel(cls.casts)).joinedload(rel(SeriesCast.user)),
            selectinload(rel(cls.veto_steps)).joinedload(rel(DBSeriesVetoStep.map)),
        )

    @classmethod
    def _eager_options(cls) -> tuple[ORMOption, ...]:
        """The rows a season report reads off every series."""
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
            selectinload(rel(cls.casts)).joinedload(rel(SeriesCast.user)),
            selectinload(rel(cls.veto_steps)).joinedload(rel(DBSeriesVetoStep.map)),
        )


# The names a series list sorts by, and the column each one orders
SERIES_SORTS: dict[SeriesSort, ColumnElement[Any]] = {
    "date_time": Series.date_time,
    "week": Match.playday,
    "id": Series.id,
}


class SeriesCreate(SeriesBase):
    # SeriesService caps a score at the maps a win takes in the season
    player1_score: int | None = Field(default=None, ge=0)
    player2_score: int | None = Field(default=None, ge=0)


class SeriesUpdate(SQLModel):
    match_id: int | None = None
    date_time: Annotated[datetime | None, AwareUTC] = None
    player1_id: int | None = None
    player2_id: int | None = None
    player1_score: int | None = Field(default=None, ge=0)
    player2_score: int | None = Field(default=None, ge=0)
    host_player_id: int | None = None
    is_fantasy_match: bool | None = None
    player1_off_race: Annotated[Race | None, SuggestRace] = None
    player2_off_race: Annotated[Race | None, SuggestRace] = None


def _pick_map(series: Series, side: str) -> str | None:
    """The map one side picked in the veto, by name; null before the pick."""
    for step in series.veto_steps:
        if step.action == "pick" and step.side == side:
            return step.map.name if step.map else None
    return None


class SeriesPublic(SeriesBase, PublicModel):
    id: int
    match_id: int | None = None
    player1_id: int | None = None
    player2_id: int | None = None
    host_player_id: int | None = None
    date_time: datetime | None = None
    match: MatchPublic | None = None
    player1: UserPublic | None = None
    player2: UserPublic | None = None
    # app.services.derived fills the points from the map scores
    player1_points: int | None = None
    player2_points: int | None = None
    # The off race a side reported, and null when he played his signup race
    player1_off_race: Annotated[str | None, EnumValue] = None
    player2_off_race: Annotated[str | None, EnumValue] = None
    # The race each side played, which app.services.derived resolves. Read only:
    # a write model names the off race, so an echoed answer cannot pin a row.
    player1_race: Annotated[str | None, EnumValue] = None
    player2_race: Annotated[str | None, EnumValue] = None
    # The map each side picked in the veto, so a series card names its games
    # without reading the whole board. Side A is player1.
    player1_pick_map: str | None = None
    player2_pick_map: str | None = None
    casts: list[CastPublic] = []

    @classmethod
    def from_series(cls, series: Series) -> Self:
        return cls(
            id=ident(series),
            match_id=series.match_id,
            match=MatchPublic.from_match(series.match) if series.match else None,
            date_time=series.date_time,
            casts=[
                CastPublic.from_cast(cast, has_result(series)) for cast in series.casts
            ],
            player1_id=series.player1_id,
            player1=UserPublic.from_user(series.player1) if series.player1 else None,
            player2_id=series.player2_id,
            player2=UserPublic.from_user(series.player2) if series.player2 else None,
            player1_score=series.player1_score,
            player2_score=series.player2_score,
            host_player_id=series.host_player_id,
            is_fantasy_match=series.is_fantasy_match,
            player1_off_race=series.player1_off_race,
            player2_off_race=series.player2_off_race,
            player1_pick_map=_pick_map(series, "A"),
            player2_pick_map=_pick_map(series, "B"),
        )

    @classmethod
    def from_series_reduced(cls, series: Series) -> Self:
        """The series with reduced players, so no player collection loads."""
        return cls(
            id=ident(series),
            match_id=series.match_id,
            match=MatchPublic.from_match(series.match) if series.match else None,
            date_time=series.date_time,
            casts=[
                CastPublic.from_cast(cast, has_result(series)) for cast in series.casts
            ],
            player1_id=series.player1_id,
            player1=UserPublic.from_user_reduced(series.player1)
            if series.player1
            else None,
            player2_id=series.player2_id,
            player2=UserPublic.from_user_reduced(series.player2)
            if series.player2
            else None,
            player1_score=series.player1_score,
            player2_score=series.player2_score,
            host_player_id=series.host_player_id,
            is_fantasy_match=series.is_fantasy_match,
            player1_off_race=series.player1_off_race,
            player2_off_race=series.player2_off_race,
            player1_pick_map=_pick_map(series, "A"),
            player2_pick_map=_pick_map(series, "B"),
        )


def has_result(series: Series | SeriesPublic) -> bool:
    """A series with a result is over: nothing is left to stream."""
    return series.player1_score is not None or series.player2_score is not None
