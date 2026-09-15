from collections.abc import Iterable
from datetime import date, datetime
from typing import TYPE_CHECKING, Annotated, Any, Literal, NamedTuple, Self

from pydantic import NonNegativeInt, PositiveInt
from sqlalchemy import (
    JSON,
    Index,
    and_,
    case,
    column,
    false,
    func,
    or_,
    select,
    table,
    text,
    true,
)
from sqlalchemy.orm import Session, column_property
from sqlmodel import Field, Relationship, SQLModel, col

from app.models.base import DBModel, ident
from app.models.enums import EntrantKind, EventKind, Race, SignupPolicy
from app.models.event_division import EventDivisionPublic
from app.models.event_stage import EventStagePublic, EventStageWrite
from app.models.map import MapPublic
from app.models.relationships import (
    DBEventRound,
    EventRoundPublic,
    SeasonRoundPublic,
)
from app.models.types import (
    AwareUTC,
    EnumValue,
    IsoDate,
    KnownScoreSystem,
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
    # How many series one fixture holds, and a fixture pairs two team
    # entrants, so it reads only on a team event. How many rounds the season has
    # is not stored: the round rows are the count.
    series_per_round: int
    pick_ban: Annotated[str | None, NumToStr] = Field(default=None, max_length=100)
    start_date: Annotated[date | None, LenientDate] = None
    end_date: Annotated[date | None, LenientDate] = None
    discordRole: Annotated[str | None, NumToStr] = Field(default=None, max_length=50)
    # One rule per game of a series: veto, loser, host or fixed
    map_rules: Annotated[str | None, MapRules] = Field(default=None, max_length=100)
    # The scale the series points use; an unknown value would re-score the season
    score_system: Annotated[str, KnownScoreSystem] = Field(
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
    # How many days before a round starts its check-in opens; blank keeps it open
    checkin_days: int | None = Field(
        default=3, ge=0, sa_column_kwargs={"server_default": "3"}
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
    # A GNL season is one event of the GNL league; "season" stays its name in the payloads
    __tablename__ = "event"
    if TYPE_CHECKING:
        # Mapped below the class, where Season.id exists; declared here so a
        # type checker sees it
        round_count: int
        league_short_name: str | None

    # The import matches a season by name, so two seasons cannot share one
    __table_args__ = (Index("uq_seasons_name", text("lower(trim(name))"), unique=True),)

    id: int | None = Field(default=None, primary_key=True)
    # The event columns. They stay off SeasonBase, so the GNL season payloads
    # keep their fields; EventPublic below is what reads them.
    league_id: int | None = Field(default=None, index=True, foreign_key="league.id")
    kind: EventKind = Field(
        default=EventKind.gnl, sa_column_kwargs={"server_default": "gnl"}
    )
    # The event this one feeds: a qualifier is a child of the event it qualifies for
    parent_id: int | None = Field(
        default=None, index=True, foreign_key="event.id", ondelete="SET NULL"
    )
    # Who may enter: a member with an account, or any battle tag
    signup_policy: SignupPolicy = Field(
        default=SignupPolicy.members, sa_column_kwargs={"server_default": "members"}
    )
    # Copied from the league when the event is created; the league may change later
    entrant_kind: EntrantKind = Field(
        default=EntrantKind.solo, sa_column_kwargs={"server_default": "solo"}
    )
    # Off: a draft only an admin sees
    published: bool = Field(default=True, sa_column_kwargs={"server_default": true()})
    # Off: the round check-in never asks, and every round stays open
    checkin_enabled: bool = Field(
        default=True, sa_column_kwargs={"server_default": true()}
    )
    # On, a player may enter once per race; each row seeds on its own race
    multi_entry: bool = Field(
        default=False, sa_column_kwargs={"server_default": false()}
    )
    # When an admin closed the event; a closed event reads finished
    closed_at: Annotated[datetime | None, AwareUTC] = Field(
        default=None, sa_type=UTCDateTime
    )
    # The rules or landing page of the event, shown as one "Page" link
    page_url: str | None = Field(default=None, max_length=500)
    stream_url: str | None = Field(default=None, max_length=500)
    # The Discord message the event card was last posted as; a repost edits it
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
    # Where the event is played, as the entrants read it
    region: str | None = Field(default=None, max_length=20)
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
    rounds: list["DBEventRound"] = Relationship(
        back_populates="season",
        sa_relationship_kwargs={
            "cascade": "all, delete",
            "order_by": "DBEventRound.number",
        },
    )

    def progress(self, session: Session) -> SeasonProgress:
        """The season's phase from its series; a season with no series is open."""
        return progress_by_seasons(session, [self])[self.id]

    signup_users: list["DBUserSeasonSignup"] = Relationship(
        back_populates="season", sa_relationship_kwargs={"cascade": "all, delete"}
    )


# The counts of an event whose series are not written yet
NO_SERIES = (0, 0, 0)


def series_counts_by_event(
    session: Session, event_ids: Iterable[int | None]
) -> dict[int | None, tuple[int, int, int]]:
    """How many series each event holds, how many started, how many are scored.

    Every series names its round and every round names its event, so the count
    joins through the round and takes a generated bracket series, which has no
    fixture, the same way as a GNL one. A series has started once it is scored
    or its time has passed; a bracket series carries no time until it is
    scheduled, so it counts as started only once it is scored. An event with no
    series has no row here.
    """
    from app.models.relationships import DBEventRound
    from app.models.series import Series

    ids = [event_id for event_id in event_ids if event_id is not None]
    if not ids:
        return {}
    scored = and_(
        col(Series.player1_score).is_not(None),
        col(Series.player2_score).is_not(None),
    )
    started = or_(scored, col(Series.date_time) <= utcnow())
    rows = session.execute(
        select(
            col(DBEventRound.season_id),
            func.count(),
            func.coalesce(func.sum(case((started, 1), else_=0)), 0),
            func.coalesce(func.sum(case((scored, 1), else_=0)), 0),
        )
        .select_from(Series)
        .join(DBEventRound, col(DBEventRound.id) == col(Series.round_id))
        .where(col(DBEventRound.season_id).in_(ids))
        .group_by(col(DBEventRound.season_id))
    ).all()
    return {row[0]: (row[1], row[2], row[3]) for row in rows}


def series_counts(session: Session, event_id: int | None) -> tuple[int, int, int]:
    """The same three counts for one event; at most one row comes back."""
    counts = series_counts_by_event(session, [event_id])
    return next(iter(counts.values()), NO_SERIES)


def progress_by_seasons(
    session: Session, seasons: Iterable["Season"]
) -> dict[int | None, SeasonProgress]:
    """The phase of every one of those seasons, from one grouped aggregate.

    Season.progress calls it for a single season, so a list answer costs one
    statement instead of one per season.
    """
    seasons = list(seasons)
    counts = series_counts_by_event(session, [season.id for season in seasons])
    return {
        season.id: _phase(season, *counts.get(season.id, NO_SERIES))
        for season in seasons
    }


def _phase(
    season: "Season", total: int, n_started: int, n_scored: int
) -> SeasonProgress:
    """The phase those series counts make; a season with no series is open."""
    unscored = total - n_scored
    if not n_started:
        return SeasonProgress("open", unscored)
    if not unscored:
        return SeasonProgress("complete", 0)
    if season.end_date and season.end_date < utcnow().date():
        return SeasonProgress("overdue", unscored)
    return SeasonProgress("commenced", unscored)


# How many rounds the season is played over: the round rows are the count, so
# nothing stores it. A scalar subquery, so it survives a noload on a nested
# season, where a relationship count would answer null or load the rows.
# The price: a query that loads a Season may not also join event_round, because
# the subquery would lose its own FROM, so a series read that wants its round
# number reads the rounds first and orders in Python (stage_engine.series_of).
ROUND_COUNT = (
    select(func.count())
    .select_from(DBEventRound)
    .where(col(DBEventRound.season_id) == Season.id)
    .scalar_subquery()
    .label("round_count")
)
Season.round_count = column_property(ROUND_COUNT)

# The short name of the league the event belongs to, so every payload that
# names an event also says which league it is part of. A scalar subquery, so a
# list of events costs one statement, not one read per row. The league table is
# spelled out here because app.models.league imports this module.
LEAGUE = table("league", column("id"), column("short_name"))
LEAGUE_SHORT_NAME = (
    select(LEAGUE.c.short_name)
    .where(LEAGUE.c.id == Season.league_id)
    .scalar_subquery()
    .label("league_short_name")
)
Season.league_short_name = column_property(LEAGUE_SHORT_NAME)


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
    score_system: Annotated[str | None, KnownScoreSystem] = None
    fantasy_grind: bool | None = None
    signups_open: bool | None = None
    scheduling_enabled: bool | None = None
    checkin_days: int | None = Field(default=None, ge=0)


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
    # The short name of the season's league; null when the event has no league
    league_short_name: Annotated[str | None, NumToStr] = None
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
            league_short_name=season.league_short_name,
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
            checkin_days=season.checkin_days,
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
            league_short_name=season.league_short_name,
            map_rules=season.map_rules,
            fantasy_grind=season.fantasy_grind,
            signups_open=season.signups_open,
            scheduling_enabled=season.scheduling_enabled,
            checkin_days=season.checkin_days,
            signup_race=signup_race,
        )

    @classmethod
    def from_season_without_maps(cls, season: Season) -> Self:
        """Every scalar field of the season, without the map pool."""
        return cls(
            id=ident(season),
            name=season.name,
            league_short_name=season.league_short_name,
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
            checkin_days=season.checkin_days,
            fantasy_tiers=tier_count(season.fantasy_tier_cuts),
            fantasy_tier_cuts=season.fantasy_tier_cuts or [],
            fantasy_tiers_applied_at=season.fantasy_tiers_applied_at,
        )


# The event phase, derived from published, the check-in window and the series;
# nothing stores it. app/services/events.py computes it.
EventPhase = Literal[
    "draft", "signups_open", "checkin", "seeded", "running", "finished"
]

# What a member checks into: one round of the event, or the event itself
CheckinShape = Literal["event", "round"]

# What the check-in shows a player for one round; app/core/checkin_hint.py reads it
AvailabilityHint = Literal["answered_yes", "answered_no", "blocked_by_blocks", "open"]

# The one action a member's event row offers; app/services/events.py computes it
MemberAction = Literal[
    "sign_up", "withdraw", "check_in", "checked_in", "view", "closed"
]


class EventPublic(SQLModel):
    """One event as the events pages read it, GNL season or not.

    The GNL payloads are SeasonPublic and stay as they are; this model is the
    one that carries the event columns. Nothing here is stored derived: the
    phase is computed from published, the check-in window and the series.
    """

    id: int
    league_id: int | None = None
    # The short name of the event's league; null when the event has no league
    league_short_name: Annotated[str | None, NumToStr] = None
    kind: EventKind = EventKind.gnl
    # The event this one feeds; a qualifier reads its parent here
    parent_id: int | None = None
    signup_policy: SignupPolicy = SignupPolicy.members
    entrant_kind: EntrantKind = EntrantKind.solo
    name: Annotated[str | None, NumToStr] = None
    description: str | None = None
    published: bool = True
    signups_open: bool = True
    scheduling_enabled: bool = True
    start_date: Annotated[IsoDate | None, LenientDate] = None
    end_date: Annotated[IsoDate | None, LenientDate] = None
    starts_at: Annotated[datetime | None, AwareUTC] = None
    checkin_enabled: bool = True
    multi_entry: bool = False
    closed_at: Annotated[datetime | None, AwareUTC] = None
    region: str | None = None
    page_url: str | None = None
    stream_url: str | None = None
    map_rules: Annotated[str | None, MapRules] = None
    min_games: int | None = None
    mmr_max: int | None = None
    entrant_cap: int | None = None
    checkin_days: int | None = None
    # How many series one fixture holds, and a fixture pairs two team
    # entrants, so it reads only on a team event.
    series_per_round: int = 1
    # The event table still carries the fields introduced for the GNL. They
    # read here as event configuration so a client never has to fetch the
    # legacy season payload for a GNL run.
    round_count: int | None = None
    pick_ban: Annotated[str | None, NumToStr] = None
    discordRole: Annotated[str | None, NumToStr] = None
    score_system: str | None = None
    fantasy_grind: bool | None = None
    fantasy_tiers: int | None = None
    fantasy_tier_cuts: Annotated[list[int], NoneToList] = []
    fantasy_tiers_applied_at: Annotated[datetime | None, AwareUTC] = None
    # The series without a score. Event phase is the canonical status; this
    # count preserves the useful part of the older season progress payload.
    unscored_series: int | None = None
    maps: Annotated[list[MapPublic], NoneToList] = []
    rounds: Annotated[list[SeasonRoundPublic], NoneToList] = []
    # Computed by the service on every read; null when the event is nested
    phase: EventPhase | None = None
    # Whether the check-in stands open today; null on a list read
    checkin_open: bool | None = None
    # The entrants who have not withdrawn; null on a list read
    entrant_count: int | None = None
    stages: list[EventStagePublic] = []
    divisions: list[EventDivisionPublic] = []
    # The events this one is the parent of, newest first; empty on a list read
    children: list["EventPublic"] = []


class EventCreate(SQLModel):
    """A new event. Its stages come from the body, or one default stage is made;
    an explicit empty list writes no stage at all."""

    name: Annotated[str, NumToStr]
    league_id: int | None = None
    kind: EventKind = EventKind.gnl
    parent_id: int | None = None
    signup_policy: SignupPolicy = SignupPolicy.members
    # Left out, the service copies the entrant kind of the league
    entrant_kind: EntrantKind | None = None
    description: str | None = None
    published: bool = True
    signups_open: bool = True
    scheduling_enabled: bool = True
    start_date: Annotated[date | None, LenientDate] = None
    end_date: Annotated[date | None, LenientDate] = None
    starts_at: Annotated[datetime | None, AwareUTC] = None
    checkin_enabled: bool = True
    # On, a player may enter once per race; each row seeds on its own race
    multi_entry: bool = False
    checkin_days: int | None = Field(default=3, ge=0)
    region: str | None = None
    page_url: str | None = None
    stream_url: str | None = None
    map_rules: Annotated[str | None, MapRules] = None
    min_games: int | None = None
    mmr_max: int | None = None
    entrant_cap: int | None = None
    # How many series one fixture holds, and a fixture pairs two team
    # entrants, so it reads only on a team event.
    series_per_round: int = 1
    # GNL configuration. The same event fields may be read for every kind;
    # the GNL league is the caller that gives them behaviour.
    round_count: int | None = Field(default=None, ge=0)
    map_ids: list[int] = []
    pick_ban: Annotated[str | None, NumToStr] = None
    discordRole: Annotated[str | None, NumToStr] = None
    score_system: Annotated[str, KnownScoreSystem] = "standard"
    fantasy_grind: bool = False
    stages: list[EventStageWrite] = []


class EventUpdate(SQLModel):
    """The event fields an admin may change. A field left out keeps its value."""

    name: Annotated[str | None, NumToStr] = None
    league_id: int | None = None
    kind: EventKind | None = None
    parent_id: int | None = None
    signup_policy: SignupPolicy | None = None
    entrant_kind: EntrantKind | None = None
    description: str | None = None
    published: bool | None = None
    signups_open: bool | None = None
    scheduling_enabled: bool | None = None
    start_date: Annotated[date | None, LenientDate] = None
    end_date: Annotated[date | None, LenientDate] = None
    starts_at: Annotated[datetime | None, AwareUTC] = None
    checkin_enabled: bool | None = None
    multi_entry: bool | None = None
    checkin_days: int | None = Field(default=None, ge=0)
    region: str | None = None
    page_url: str | None = None
    stream_url: str | None = None
    map_rules: Annotated[str | None, MapRules] = None
    min_games: int | None = None
    mmr_max: int | None = None
    entrant_cap: int | None = None
    series_per_round: int | None = None
    round_count: int | None = Field(default=None, ge=0)
    pick_ban: Annotated[str | None, NumToStr] = None
    discordRole: Annotated[str | None, NumToStr] = None
    score_system: Annotated[str | None, KnownScoreSystem] = None
    fantasy_grind: bool | None = None


class EventDiscordPost(SQLModel):
    """The channel an admin posts the event card in."""

    channel_id: Annotated[str, NumToStr]


class MemberEventRow(SQLModel):
    """One row of the member home's events list, over every kind of event.

    It replaces the season and KOTH split: the rows are keyed by event id,
    which no longer collides now that a KOTH night is an event too.
    """

    kind: EventKind
    id: int
    name: Annotated[str | None, NumToStr] = None
    # The short name of the event's league; null when the event has no league
    league_short_name: Annotated[str | None, NumToStr] = None
    start: Annotated[IsoDate | None, LenientDate] = None
    end: Annotated[IsoDate | None, LenientDate] = None
    phase: EventPhase
    signups_open: bool
    # The caller holds an entrant row, or a GNL signup, for this event
    joined: bool
    # The event's optional "Page" link; the home builds its own in-app link
    url: str | None = None
    # The caller's own entrant row; null for a GNL signup, which holds no entrant
    entrant_id: int | None = None
    # When the caller checked in; null while the check-in is not taken. The
    # event shape reads the entrant stamp, the round shape the caller's round
    # answer, which carries no time and reports when its window opened
    checked_in_at: Annotated[datetime | None, AwareUTC] = None
    # What the caller checks into: the round when the event's next round carries
    # dates, else the event; null when the event takes no check-in
    checkin_shape: CheckinShape | None = None
    # That shape's check-in window stands open today
    checkin_open: bool = False
    # The next round of the event that carries dates; null when none does
    next_round: EventRoundPublic | None = None
    # What the next round's check-in shows the caller; null off the round shape
    availability_hint: AvailabilityHint | None = None
    # The one action the page offers the caller, from the phase, the signup
    # window, the caller's entrant or GNL signup and the check-in window:
    # `sign_up` signups are open and the caller has not entered; `withdraw` the
    # caller is in and the check-in is not open; `check_in` the window stands
    # open; `checked_in` the caller checked in already; `view` the event runs or
    # is finished, so the page reads the bracket or the standings; `closed`
    # nothing is open to the caller yet.
    action: MemberAction
