from datetime import date, datetime
from typing import TYPE_CHECKING, Annotated, Any, Literal, NamedTuple, Self

from pydantic import NonNegativeInt, PositiveInt, model_validator
from sqlalchemy import JSON, Index, and_, case, false, func, or_, select, text
from sqlalchemy.orm import Session
from sqlmodel import Field, Relationship, SQLModel, col

from app.models.base import DBModel, ident
from app.models.enums import Race
from app.models.map import MapPublic
from app.models.relationships import SeasonRoundPublic
from app.models.types import (
    AwareUTC,
    EnumValue,
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
        DBSeasonRound,
        DBUserSeasonSignup,
    )
    from app.models.team_season import DBTeamSeason
    from app.models.user_team_season import DBUserTeamSeason


# The round columns and the week columns they replace
ROUND_NAMES = (
    ("number_rounds", "number_weeks"),
    ("series_per_round", "series_per_week"),
)


class RoundCounts(SQLModel):
    """How many rounds a season is played over, and how many series each player
    plays per round. A round is one or two weeks, so the week names are wrong.
    They stay filled and readable until the deploy after the readers move off."""

    number_rounds: int | None = None
    series_per_round: int | None = None
    number_weeks: int | None = None
    series_per_week: int | None = None

    @model_validator(mode="after")
    def fill_the_other_name(self) -> Self:
        """Either name fills the other, so an old client still writes both."""
        for new_name, old_name in ROUND_NAMES:
            new_value, old_value = getattr(self, new_name), getattr(self, old_name)
            # A name left out of a partial update stays out of it, or the write
            # would set the column to null
            if new_value is None and old_value is not None:
                self._set(new_name, old_value)
            elif old_value is None and new_value is not None:
                self._set(old_name, new_value)
        return self

    def _set(self, name: str, value: int) -> None:
        setattr(self, name, value)
        # model_dump(exclude_unset=True) writes a column only when it is set
        self.__pydantic_fields_set__.add(name)


class SeasonBase(RoundCounts):
    name: Annotated[str, NumToStr] = Field(max_length=50)
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
    # Whether the season offers the fantasy grind pick: a second team, paid by rank
    fantasy_grind: bool = Field(
        default=False, sa_column_kwargs={"server_default": false()}
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
    rounds: list["DBSeasonRound"] = Relationship(
        back_populates="season",
        sa_relationship_kwargs={
            "cascade": "all, delete",
            "order_by": "DBSeasonRound.playday",
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


class SeasonUpdate(RoundCounts):
    name: Annotated[str | None, NumToStr] = None
    pick_ban: Annotated[str | None, NumToStr] = None
    start_date: Annotated[date | None, LenientDate] = None
    end_date: Annotated[date | None, LenientDate] = None
    discordRole: Annotated[str | None, NumToStr] = None
    map_rules: Annotated[str | None, MapRules] = None
    score_system: str | None = None
    fantasy_grind: bool | None = None


class SeasonTeamIds(SQLModel):
    team_ids: list[int]


class SeasonMapIds(SQLModel):
    map_ids: list[int]


class FantasyTierAllocation(SQLModel):
    """One season's whole tier allocation: the cuts and every tiered player."""

    cuts: list[int]
    tiers: dict[int, PositiveInt]


class SeasonSignupRemove(SQLModel):
    """The users to remove from a season."""

    user_ids: list[int]


class SeasonSignupWrite(SeasonSignupRemove):
    """The users to sign up, all on the race they registered on."""

    race: str


class SeasonSignupUpdate(SQLModel):
    """The draft fields of one signup. A null position sorts the player by MMR."""

    draft_position: NonNegativeInt | None = None
    # The race the player registered on; a field left out keeps it, null is refused
    race: str | None = None


class SeasonPublic(SeasonBase):
    id: int
    # The short form of a season carries only the name, so these read null
    score_system: str | None = None
    fantasy_grind: bool | None = None
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
    rounds: Annotated[list[SeasonRoundPublic], NoneToList] = []
    # Always empty; the public pages read this field
    user_signup: Annotated[list[Any], NoneToList] = []
    # The race of the signup this season is nested under; null everywhere else
    signup_race: Annotated[str | None, EnumValue] = None

    @classmethod
    def from_season(cls, season: Season) -> Self:
        return cls(
            id=ident(season),
            name=season.name,
            number_rounds=season.number_rounds,
            series_per_round=season.series_per_round,
            pick_ban=season.pick_ban,
            start_date=season.start_date,
            end_date=season.end_date,
            maps=[
                MapPublic.model_validate(map_season.map)
                for map_season in (season.maps or [])
                if map_season and map_season.map
            ],
            rounds=[SeasonRoundPublic.from_row(row) for row in (season.rounds or [])],
            discordRole=season.discordRole,
            map_rules=season.map_rules,
            score_system=season.score_system,
            fantasy_grind=season.fantasy_grind,
            fantasy_tiers=tier_count(season.fantasy_tier_cuts),
            fantasy_tier_cuts=season.fantasy_tier_cuts or [],
            fantasy_tiers_applied_at=season.fantasy_tiers_applied_at,
        )

    @classmethod
    def from_season_reduced(
        cls, season: Season, signup_race: Race | None = None
    ) -> Self:
        """The name, the id, the map rules and the grind flag only. Used where
        a season is a label on another object rather than the subject."""
        return cls(
            id=ident(season),
            name=season.name,
            map_rules=season.map_rules,
            fantasy_grind=season.fantasy_grind,
            signup_race=signup_race,
        )

    @classmethod
    def from_season_without_maps(cls, season: Season) -> Self:
        """Every scalar field of the season, without the map pool."""
        return cls(
            id=ident(season),
            name=season.name,
            number_rounds=season.number_rounds,
            series_per_round=season.series_per_round,
            pick_ban=season.pick_ban,
            start_date=season.start_date,
            end_date=season.end_date,
            discordRole=season.discordRole,
            map_rules=season.map_rules,
            score_system=season.score_system,
            fantasy_grind=season.fantasy_grind,
            fantasy_tiers=tier_count(season.fantasy_tier_cuts),
            fantasy_tier_cuts=season.fantasy_tier_cuts or [],
            fantasy_tiers_applied_at=season.fantasy_tiers_applied_at,
        )
