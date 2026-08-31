"""The shapes GET /player-history sends.

Nothing here is a table. app.services.player_history derives every number
from the series the player stood in.
"""

from datetime import datetime

from sqlmodel import SQLModel


class HistoryMeeting(SQLModel):
    """One played series against the opponent."""

    series_id: int
    season_id: int
    season_name: str | None = None
    playday: int | None = None
    my_score: int
    their_score: int
    date_time: datetime | None = None


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
    """One season the player took part in."""

    season_id: int
    season_name: str | None = None
    team_id: int | None = None
    team_name: str | None = None
    played: int
    won: int
    lost: int
    # Where the team finished by the points it scored, and how many teams stood
    place: int | None = None
    team_count: int | None = None
    running: bool = False


class PlayerHistory(SQLModel):
    events: list[HistoryEvent]
    opponents: list[HistoryOpponent]
