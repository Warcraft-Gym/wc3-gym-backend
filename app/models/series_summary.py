"""The list row of an event's fixture series.

Nothing here is a table. app.services.series_summary computes every field in
SQL; only the two players and the casts are built in Python.
"""

from datetime import datetime
from typing import Annotated

from sqlmodel import SQLModel

from app.models.types import AwareUTC


class SeriesPlayerPublic(SQLModel):
    """One side of a series: the player and the race he played."""

    id: int
    name: str
    # The off race, else the signup race, as SeriesPublic resolves each side
    race: str | None = None


class SeriesCastSummaryPublic(SQLModel):
    """One cast of a series, named and linked as CastPublic names it."""

    id: int
    # The account's name, or the channel for a cast with no account
    name: str
    channel_url: str
    # The pasted URL, or the channel when it is itself the video of a scored series
    vod_url: str | None = None


class SeriesSummaryPublic(SQLModel):
    """One fixture series of an event, flat.

    A fixture series belongs to a match of the event and names no entrant on
    either side; a stage or round series is not one. The match and its teams
    are read once from GET /events/{event_id}/matches by match_id.
    """

    id: int
    season_id: int
    match_id: int
    # The playday of the match
    week: int | None = None
    date_time: Annotated[datetime | None, AwareUTC] = None
    player1: SeriesPlayerPublic | None = None
    player2: SeriesPlayerPublic | None = None
    player1_score: int | None = None
    player2_score: int | None = None
    # The points each side takes on the season's score system and best-of
    player1_points: int | None = None
    player2_points: int | None = None
    casts: list[SeriesCastSummaryPublic] = []
