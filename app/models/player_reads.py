"""The shapes of a player's own reads: his summary, his seasons and his series.

Nothing here is a table. app.services.player_reads computes every field in SQL,
from the player's side of each row.
"""

from datetime import datetime

from sqlmodel import SQLModel

from app.models.team_summary import TeamSummaryPublic
from app.models.w3c_stats import RaceMmr


class PlayerSummaryPublic(SQLModel):
    """The person a player page names: his tags and his ladder summary."""

    id: int
    name: str
    # The active tag's text, null with no tag
    battleTag: str | None = None
    country: str | None = None
    # The text of every tag the person holds, the active one first
    tags: list[str] = []
    # The ladder summary with the stale races, as GET /users/{key} serves it
    race_mmrs: list[RaceMmr] = []
    # The window race with the top mmr and 10 or more window games, else null
    main_race: str | None = None


class PlayerSeasonRecordPublic(SQLModel):
    """The player's series in one season, counted as gnl_stats counts them."""

    games: int = 0
    wins: int = 0
    losses: int = 0
    # The race of each opponent in playday order; null where he has no signup
    matchup_history: list[str | None] = []


class PlayerSeasonPublic(SQLModel):
    """One season the player held a roster or a captain seat in."""

    season_id: int
    # The roster team, else the captained team
    team: TeamSummaryPublic | None = None
    is_captain: bool = False
    captain_only: bool = False
    signup_race: str | None = None
    played_as: str | None = None
    record: PlayerSeasonRecordPublic


class PlayerSeriesSummaryPublic(SQLModel):
    """One GNL series from the player's side, flat."""

    id: int
    season_id: int
    week: int | None = None
    date_time: datetime | None = None
    # The off race, else the signup race, as SeriesPublic resolves each side
    race: str | None = None
    score: int | None = None
    opponent_score: int | None = None
    opponent_id: int | None = None
    opponent_name: str | None = None
    opponent_race: str | None = None
    # The fixture's teams: long_name when set, else name
    team1_name: str | None = None
    team2_name: str | None = None
    # The first cast with a VOD, else the first cast
    cast_id: int | None = None
    cast_name: str | None = None
    cast_channel_url: str | None = None
    cast_vod_url: str | None = None
