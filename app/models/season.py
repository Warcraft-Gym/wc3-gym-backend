from collections.abc import Sequence
from datetime import date, datetime
from typing import TYPE_CHECKING, Annotated, Any, Literal, NamedTuple, Self

from pydantic import NonNegativeInt, PositiveInt
from sqlalchemy import JSON, Index, and_, case, false, func, or_, select, text, true
from sqlalchemy.orm import Session, column_property
from sqlmodel import Field, Relationship, SQLModel, col

from app.models.base import DBModel, ident
from app.models.enums import EventKind, Race
from app.models.event_division import EventDivisionPublic
from app.models.event_stage import EventStagePublic
from app.models.map import MapPublic
from app.models.relationships import DBSeasonRound, SeasonRoundPublic
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
        DBUserSeasonSignup,
    )
    from app.models.team_season import DBTeamSeason
    from app.models.user_team_season import DBUserTeamSeason


class SeasonBase(SQLModel):
    name: Annotated[str, NumToStr] = Field(max_length=50)
    # How many series each player plays per round. How many rounds the season
    # has is not stored: the round rows are the count.
    series_per_round: int
    pick_ban: Annotated[str | None, NumToStr] = Field(default=None, max_length=100)
    start_date: Annotated[date | None, LenientDate] = None
    end_date: Annotated[date | None, LenientDate] = None
    discordRole: Annotated[str | None, NumToStr] = Field(default=None, max_length=50)
    # One rule per game of a series: veto, loser, host or fixed
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
    # Off: a signup to the season is a request an admin may grant
    signups_open: bool = Field(
        default=True, sa_column_kwargs={"server_default": true()}
    )
    # Off: the event takes no availability answers
    scheduling_enabled: bool = Field(
        default=True, sa_column_kwargs={"server_default": true()}
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


def series_counts(session: Session, event_id: int | None) -> tuple[int, int, int]:
    """How many series the event holds, how many have started, how many are scored."""
    if event_id is None:
        return 0, 0, 0
    return series_counts_by_event(session, [event_id]).get(event_id, (0, 0, 0))


def series_counts_by_event(
    session: Session, event_ids: Sequence[int | None]
) -> dict[int, tuple[int, int, int]]:
    """The same three counts per event, in one query, for a page of events.

    A series has started once it is scored or its time has passed. The series
    of an event still hang off its matches, so the count joins through them.
    An event with no series has no row here.
    """
    from app.models.match import Match
    from app.models.series import Series

    scored = and_(
        col(Series.player1_score).is_not(None),
        col(Series.player2_score).is_not(None),
    )
    started = or_(scored, col(Series.date_time) <= utcnow())
    rows = session.execute(
        select(
            col(Match.season_id),
            func.count(),
            func.coalesce(func.sum(case((started, 1), else_=0)), 0),
            func.coalesce(func.sum(case((scored, 1), else_=0)), 0),
        )
        .select_from(Series)
        .join(Match, col(Match.id) == col(Series.match_id))
        .where(col(Match.season_id).in_([i for i in event_ids if i is not None]))
        .group_by(col(Match.season_id))
    )
    return {row[0]: (row[1], row[2], row[3]) for row in rows}


# The event phase, derived from published, the check-in window and the series
# (NE-9); nothing stores it. app/services/events.py computes it.
EventPhase = Literal[
    "draft", "signups_open", "checkin", "seeded", "running", "finished"
]


class Season(SeasonBase, DBModel, table=True):
    # A GNL season is one event of the GNL league; "season" stays its name in the payloads
    __tablename__ = "event"
    if TYPE_CHECKING:
        # Mapped below the class, where Season.id exists; declared here so a
        # type checker sees it
        round_count: int

    # The import matches a season by name, so two seasons cannot share one
    __table_args__ = (Index("uq_seasons_name", text("lower(trim(name))"), unique=True),)

    id: int | None = Field(default=None, primary_key=True)
    # The event columns. They stay off SeasonBase, so the GNL season payloads
    # keep their fields; EventPublic below is what reads them.
    league_id: int | None = Field(default=None, index=True, foreign_key="league.id")
    kind: EventKind = Field(
        default=EventKind.gnl, sa_column_kwargs={"server_default": "gnl"}
    )
    # Off: a draft only an admin sees
    published: bool = Field(default=True, sa_column_kwargs={"server_default": true()})
    checkin_opens_at: Annotated[datetime | None, AwareUTC] = Field(
        default=None, sa_type=UTCDateTime
    )
    checkin_closes_at: Annotated[datetime | None, AwareUTC] = Field(
        default=None, sa_type=UTCDateTime
    )
    # The rules or landing page of the event, shown as one "Page" link
    page_url: str | None = Field(default=None, max_length=500)
    stream_url: str | None = Field(default=None, max_length=500)
    # The guild scheduled event this one posted, so a repost edits it
    discord_event_id: Annotated[str | None, NumToStr] = Field(
        default=None, max_length=50
    )
    description: str | None = Field(default=None, max_length=2000)
    # A cup or a KOTH night starts at a time; a GNL season keeps its dates
    starts_at: Annotated[datetime | None, AwareUTC] = Field(
        default=None, sa_type=UTCDateTime
    )
    # Eligibility bounds. They warn on the entrant row and never refuse a signup.
    min_games: int | None = None
    mmr_max: int | None = None
    entrant_cap: int | None = None
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
        total, n_started, n_scored = series_counts(session, self.id)
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


# How many rounds the season is played over: the round rows are the count, so
# nothing stores it. A scalar subquery, so it survives a noload on a nested season.
ROUND_COUNT = (
    select(func.count())
    .select_from(DBSeasonRound)
    .where(col(DBSeasonRound.season_id) == Season.id)
    .scalar_subquery()
    .label("round_count")
)
Season.round_count = column_property(ROUND_COUNT)


class SeasonCreate(SeasonBase):
    # How many rounds to make. Nothing stores it; the round rows are the count.
    round_count: int | None = None


class SeasonUpdate(SQLModel):
    name: Annotated[str | None, NumToStr] = None
    series_per_round: int | None = None
    # How many rounds to keep. Nothing stores it; the round rows are the count.
    round_count: int | None = None
    pick_ban: Annotated[str | None, NumToStr] = None
    start_date: Annotated[date | None, LenientDate] = None
    end_date: Annotated[date | None, LenientDate] = None
    discordRole: Annotated[str | None, NumToStr] = None
    map_rules: Annotated[str | None, MapRules] = None
    score_system: str | None = None
    fantasy_grind: bool | None = None
    signups_open: bool | None = None
    scheduling_enabled: bool | None = None


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
    # True takes the player out of the pick list; a field left out keeps the flag
    draft_excluded: bool = False
    # The race the player registered on; a field left out keeps it, null is refused
    race: str | None = None


class SeasonPublic(SeasonBase):
    id: int
    # How many rounds the season has, counted from its round rows
    round_count: int | None = None
    # The short form of a season carries only the name, so these read null
    series_per_round: int | None = None
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
            round_count=season.round_count,
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
            signups_open=season.signups_open,
            scheduling_enabled=season.scheduling_enabled,
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
            signups_open=season.signups_open,
            scheduling_enabled=season.scheduling_enabled,
            signup_race=signup_race,
        )

    @classmethod
    def from_season_without_maps(cls, season: Season) -> Self:
        """Every scalar field of the season, without the map pool."""
        return cls(
            id=ident(season),
            name=season.name,
            round_count=season.round_count,
            series_per_round=season.series_per_round,
            pick_ban=season.pick_ban,
            start_date=season.start_date,
            end_date=season.end_date,
            discordRole=season.discordRole,
            map_rules=season.map_rules,
            score_system=season.score_system,
            fantasy_grind=season.fantasy_grind,
            signups_open=season.signups_open,
            scheduling_enabled=season.scheduling_enabled,
            fantasy_tiers=tier_count(season.fantasy_tier_cuts),
            fantasy_tier_cuts=season.fantasy_tier_cuts or [],
            fantasy_tiers_applied_at=season.fantasy_tiers_applied_at,
        )


class EventPublic(SQLModel):
    """One event as the events pages read it, GNL season or not.

    The GNL payloads are SeasonPublic and stay as they are; this model is the
    one that carries the event columns. Nothing here is stored derived: the
    phase is computed from published, the check-in window and the series.
    """

    id: int
    league_id: int | None = None
    kind: EventKind = EventKind.gnl
    name: Annotated[str | None, NumToStr] = None
    description: str | None = None
    published: bool = True
    signups_open: bool = True
    scheduling_enabled: bool = True
    start_date: Annotated[IsoDate | None, LenientDate] = None
    end_date: Annotated[IsoDate | None, LenientDate] = None
    starts_at: Annotated[datetime | None, AwareUTC] = None
    checkin_opens_at: Annotated[datetime | None, AwareUTC] = None
    checkin_closes_at: Annotated[datetime | None, AwareUTC] = None
    page_url: str | None = None
    stream_url: str | None = None
    discord_event_id: Annotated[str | None, NumToStr] = None
    map_rules: Annotated[str | None, MapRules] = None
    min_games: int | None = None
    mmr_max: int | None = None
    entrant_cap: int | None = None
    # Computed by the service when the event is the subject; null when nested
    phase: EventPhase | None = None
    # The entrants who have not withdrawn; null on a list read
    entrant_count: int | None = None
    stages: list[EventStagePublic] = []
    divisions: list[EventDivisionPublic] = []


class MemberEventRow(SQLModel):
    """One row of the member home's events list, over every kind of event.

    It replaces the season and KOTH split: the rows are keyed by event id,
    which no longer collides now that a KOTH night is an event too.
    """

    kind: EventKind
    id: int
    name: Annotated[str | None, NumToStr] = None
    start: Annotated[IsoDate | None, LenientDate] = None
    end: Annotated[IsoDate | None, LenientDate] = None
    phase: EventPhase
    signups_open: bool
    # The caller holds an entrant row, or a GNL signup, for this event
    joined: bool
    # The event's optional "Page" link; the home builds its own in-app link
    url: str | None = None
