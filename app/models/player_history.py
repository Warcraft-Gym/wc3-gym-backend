"""The shapes GET /player-history sends.

Nothing here is a table. app.services.player_history derives every number
from the series the player stood in.
"""

from datetime import datetime

from sqlmodel import SQLModel

from app.models.enums import EventKind


class HistoryMeeting(SQLModel):
    """One played series against the opponent."""

    series_id: int
    season_id: int
    season_name: str | None = None
    # The short name of the season's league; null when the event has no league
    league_short_name: str | None = None
    # The kind of event the series was played in
    kind: EventKind = EventKind.gnl
    playday: int | None = None
    my_score: int
    their_score: int
    date_time: datetime | None = None
    # The race each side played in this meeting: the off race, else the signup race.
    my_race: str | None = None
    their_race: str | None = None
    # The maps of the series: the match's fixed map, then the veto picks.
    # Who won which map is not stored anywhere, so this is a list of names only.
    maps: list[str] = []


class HistoryOpponent(SQLModel):
    """Every series one opponent and the player ever played, over all seasons."""

    id: int
    name: str | None = None
    race: str | None = None
    country: str | None = None
    played: int
    won: int
    lost: int
    last_season_name: str | None = None
    last_playday: int | None = None
    meetings: list[HistoryMeeting] = []


class HistoryEvent(SQLModel):
    """One event the player took part in, of any kind."""

    season_id: int
    season_name: str | None = None
    # The short name of the season's league; null when the event has no league
    league_short_name: str | None = None
    # What the event is: a GNL season, a cup, a KOTH night
    kind: EventKind = EventKind.gnl
    team_id: int | None = None
    team_name: str | None = None
    played: int
    won: int
    lost: int
    # Where the team finished by the points it scored, and how many teams stood
    place: int | None = None
    team_count: int | None = None
    running: bool = False
    # The race the player signed this season up on; null when they never did
    signup_race: str | None = None


class PlayerHistory(SQLModel):
    events: list[HistoryEvent]
    opponents: list[HistoryOpponent]
