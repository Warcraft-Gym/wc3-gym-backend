"""The shapes of the home hub read.

The hub prints series of every event kind side by side, so a row carries the
context label in parts and nothing the card does not draw. The player shape is
this read's own: the reduced user of the other list reads carries stats, links
and stamps the hub never prints, and the hub answers three lists in one request.
"""

from datetime import datetime
from typing import Self

from app.models.base import PublicModel
from app.models.series import SeriesPublic
from app.models.series_cast import CastPublic
from app.models.team_reduced import TeamReduced
from app.models.user import UserPublic


class HomePlayer(PublicModel):
    """One side of a home hub row: who plays, on which race, at which rating."""

    id: int
    name: str | None = None
    country: str | None = None
    # The race the row names, and the W3Champions rating on it
    race: str | None = None
    mmr: int | None = None


class HomeTeam(PublicModel):
    """The team behind a side: what the card prints and what it links to.

    The shared reduced team also carries the league and the long name, which
    no hub card draws, and the answer holds up to twelve rows.
    """

    id: int
    name: str | None = None
    icon_url: str | None = None

    @classmethod
    def from_reduced(cls, team: TeamReduced | None) -> Self | None:
        if team is None:
            return None
        return cls(id=team.id, name=team.name, icon_url=team.icon_url)


class HomeCast(PublicModel):
    """The caster of a row and the one link its button opens."""

    name: str
    # The VOD of a played series, else the channel the caster streams on
    url: str


class HomeSeriesRow(PublicModel):
    """One series as a home hub card prints it."""

    id: int
    date_time: datetime | None = None
    # The context label in parts: "{league} - {event} - {stage} - {round}"
    league: str | None = None
    event: str | None = None
    stage: str | None = None
    round: str | None = None
    # The two teams of a fixture; null on a series the entrants play themselves
    team1: HomeTeam | None = None
    team2: HomeTeam | None = None
    player1: HomePlayer | None = None
    player2: HomePlayer | None = None
    player1_score: int | None = None
    player2_score: int | None = None
    cast: HomeCast | None = None

    @classmethod
    def from_series(
        cls,
        series: SeriesPublic,
        *,
        league: str | None,
        event: str | None,
        stage: str | None,
        round_name: str | None,
    ) -> Self:
        match = series.match
        return cls(
            id=series.id,
            date_time=series.date_time,
            league=league,
            event=event,
            stage=stage,
            round=round_name,
            team1=HomeTeam.from_reduced(match.team1) if match else None,
            team2=HomeTeam.from_reduced(match.team2) if match else None,
            player1=_side(series.player1, series.player1_race, series.player1_mmr),
            player2=_side(series.player2, series.player2_race, series.player2_mmr),
            player1_score=series.player1_score,
            player2_score=series.player2_score,
            cast=_cast(series.casts),
        )


class HomeSeries(PublicModel):
    """The three series lists the home hub draws, in one answer."""

    next: list[HomeSeriesRow] = []
    casts_upcoming: list[HomeSeriesRow] = []
    casts_recent: list[HomeSeriesRow] = []


def _side(
    player: UserPublic | None, race: str | None, mmr: int | None
) -> HomePlayer | None:
    """The player of one side, reduced to the four fields a card prints."""
    if player is None:
        return None
    return HomePlayer(
        id=player.id, name=player.name, country=player.country, race=race, mmr=mmr
    )


def _cast(casts: list[CastPublic]) -> HomeCast | None:
    """The one cast a card names: the first that holds a VOD, else the first claim."""
    if not casts:
        return None
    cast = next((row for row in casts if row.vod_url), casts[0])
    return HomeCast(name=cast.name, url=cast.vod_url or cast.channel_url)
