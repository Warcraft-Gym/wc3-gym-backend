from datetime import date, datetime
from typing import TYPE_CHECKING, Annotated, Any, Literal, NamedTuple, Self

from pydantic import PositiveInt
from sqlalchemy import JSON, Index, and_, case, func, or_, select, text
from sqlalchemy.orm import Session
from sqlmodel import Field, Relationship, SQLModel, col

from app.models.base import DBModel, ident
from app.models.map import MapPublic
from app.models.relationships import SeasonWeekMapPublic
from app.models.types import (
    AwareUTC,
    IsoDate,
    LenientDate,
    MapRules,
    NoneToList,
    NumToStr,
    UTCDateTime,
    utcnow,
)

if TYPE_CHECKING:
    from app.models.relationships import (
        DBMapSeason,
        DBSeasonWeekMap,
        DBUserSeasonSignup,
    )
    from app.models.team_season import DBTeamSeason
    from app.models.user_team_season import DBUserTeamSeason


class SeasonBase(SQLModel):
    name: Annotated[str, NumToStr] = Field(max_length=50)
    number_weeks: int
    series_per_week: int
    pick_ban: Annotated[str | None, NumToStr] = Field(default=None, max_length=100)
    start_date: Annotated[date | None, LenientDate] = None
    end_date: Annotated[date | None, LenientDate] = None
    discordRole: Annotated[str | None, NumToStr] = Field(default=None, max_length=50)
    # One rule per game of a series: veto, loser, host or week
    map_rules: Annotated[str | None, MapRules] = Field(default=None, max_length=100)
    # The scale the series points use: "standard" or "helpstone"
    score_system: str = Field(
        default="standard",
        max_length=20,
        sa_column_kwargs={"server_default": "standard"},
    )


def tier_count(cuts: list[int] | None) -> int:
    """How many fantasy tiers the cuts make, 0 before the first allocation."""
    return len(cuts) + 1 if cuts else 0


def tier_of(mmr: int, cuts: list[int]) -> int:
    """The tier an MMR falls in: tier 1 opens at the last cut, the lowest below the first."""
    return len(cuts) + 1 - sum(mmr >= cut for cut in cuts)


# Derived from the series, never stored: open until one is scored or past its time,
# complete once every one has a result, overdue past the end date with results missing
SeasonPhase = Literal["open", "commenced", "overdue", "complete"]


class SeasonProgress(NamedTuple):
    phase: SeasonPhase
    # The series that still carry no result
    unscored_series: int


class Season(SeasonBase, DBModel, table=True):
    __tablename__ = "seasons"
    # The import matches a season by name, so two seasons cannot share one
    __table_args__ = (Index("uq_seasons_name", text("lower(trim(name))"), unique=True),)

    id: int | None = Field(default=None, primary_key=True)
    # The ascending MMR each fantasy tier opens at; the tier count is one more
    fantasy_tier_cuts: list[int] | None = Field(default=None, sa_type=JSON)
    # When the tiers were applied; an unpinned tier derives from the MMR on this date
    fantasy_tiers_applied_at: Annotated[datetime | None, AwareUTC] = Field(
        default=None, sa_type=UTCDateTime
    )
    user_teams: list["DBUserTeamSeason"] = Relationship(
        back_populates="season", sa_relationship_kwargs={"cascade": "all, delete"}
    )
    teams: list["DBTeamSeason"] = Relationship(
        back_populates="season", sa_relationship_kwargs={"cascade": "all, delete"}
    )
    maps: list["DBMapSeason"] = Relationship(
        back_populates="season",
        sa_relationship_kwargs={
            "cascade": "all, delete",
            "order_by": "DBMapSeason.position",
        },
    )
    week_maps: list["DBSeasonWeekMap"] = Relationship(
        back_populates="season",
        sa_relationship_kwargs={
            "cascade": "all, delete",
            "order_by": "DBSeasonWeekMap.playday",
        },
    )

    def progress(self, session: Session) -> SeasonProgress:
        """The season's phase from its series; a season with no series is open."""
        from app.models.match import Match
        from app.models.series import Series

        scored = and_(
            col(Series.player1_score).is_not(None),
            col(Series.player2_score).is_not(None),
        )
        started = or_(scored, col(Series.date_time) <= utcnow())
        total, n_started, n_scored = session.execute(
            select(
                func.count(),
                func.coalesce(func.sum(case((started, 1), else_=0)), 0),
                func.coalesce(func.sum(case((scored, 1), else_=0)), 0),
            )
            .select_from(Series)
            .join(Match, col(Match.id) == col(Series.match_id))
            .where(col(Match.season_id) == self.id)
        ).one()
        unscored = total - n_scored
        if not n_started:
            return SeasonProgress("open", unscored)
        if not unscored:
            return SeasonProgress("complete", 0)
        if self.end_date and self.end_date < utcnow().date():
            return SeasonProgress("overdue", unscored)
        return SeasonProgress("commenced", unscored)

    signup_users: list["DBUserSeasonSignup"] = Relationship(
        back_populates="season", sa_relationship_kwargs={"cascade": "all, delete"}
    )


class SeasonCreate(SeasonBase):
    pass


class SeasonUpdate(SQLModel):
    name: Annotated[str | None, NumToStr] = None
    number_weeks: int | None = None
    series_per_week: int | None = None
    pick_ban: Annotated[str | None, NumToStr] = None
    start_date: Annotated[date | None, LenientDate] = None
    end_date: Annotated[date | None, LenientDate] = None
    discordRole: Annotated[str | None, NumToStr] = None
    map_rules: Annotated[str | None, MapRules] = None
    score_system: str | None = None


class SeasonTeamIds(SQLModel):
    team_ids: list[int]


class SeasonMapIds(SQLModel):
    map_ids: list[int]


class SeasonLadderMapNames(SQLModel):
    names: list[str]


class FantasyTierAllocation(SQLModel):
    """One season's whole tier allocation: the cuts and every tiered player."""

    cuts: list[int]
    tiers: dict[int, PositiveInt]


class SeasonSignupWrite(SQLModel):
    """The users to sign up or remove. A removal ignores the race."""

    user_ids: list[int]
    race: str | None = None


class SeasonPublic(SeasonBase):
    id: int
    # The short form of a season carries only the name, so these read null
    number_weeks: int | None = None
    series_per_week: int | None = None
    score_system: str | None = None
    # Derived: one more than the cuts, 0 until the season is allocated
    fantasy_tiers: int | None = None
    fantasy_tier_cuts: Annotated[list[int], NoneToList] = []
    fantasy_tiers_applied_at: Annotated[datetime | None, AwareUTC] = None
    # Derived from the series when the season is the subject; null when nested
    phase: SeasonPhase | None = None
    unscored_series: int | None = None
    start_date: Annotated[IsoDate | None, LenientDate] = None
    end_date: Annotated[IsoDate | None, LenientDate] = None
    maps: Annotated[list[MapPublic], NoneToList] = []
    week_maps: Annotated[list[SeasonWeekMapPublic], NoneToList] = []
    # Always empty; the public pages read this field
    user_signup: Annotated[list[Any], NoneToList] = []

    @classmethod
    def from_season(cls, season: Season) -> Self:
        return cls(
            id=ident(season),
            name=season.name,
            number_weeks=season.number_weeks,
            series_per_week=season.series_per_week,
            pick_ban=season.pick_ban,
            start_date=season.start_date,
            end_date=season.end_date,
            maps=[
                MapPublic.model_validate(map_season.map)
                for map_season in (season.maps or [])
                if map_season and map_season.map
            ],
            week_maps=[
                SeasonWeekMapPublic.from_row(row) for row in (season.week_maps or [])
            ],
            discordRole=season.discordRole,
            map_rules=season.map_rules,
            score_system=season.score_system,
            fantasy_tiers=tier_count(season.fantasy_tier_cuts),
            fantasy_tier_cuts=season.fantasy_tier_cuts or [],
            fantasy_tiers_applied_at=season.fantasy_tiers_applied_at,
        )

    @classmethod
    def from_season_reduced(cls, season: Season) -> Self:
        """The name and the id only. Used where a season is a label on
        another object rather than the subject of the response."""
        return cls(id=ident(season), name=season.name)

    @classmethod
    def from_season_without_maps(cls, season: Season) -> Self:
        """Every scalar field of the season, without the map pool."""
        return cls(
            id=ident(season),
            name=season.name,
            number_weeks=season.number_weeks,
            series_per_week=season.series_per_week,
            pick_ban=season.pick_ban,
            start_date=season.start_date,
            end_date=season.end_date,
            discordRole=season.discordRole,
            map_rules=season.map_rules,
            score_system=season.score_system,
            fantasy_tiers=tier_count(season.fantasy_tier_cuts),
            fantasy_tier_cuts=season.fantasy_tier_cuts or [],
            fantasy_tiers_applied_at=season.fantasy_tiers_applied_at,
        )
