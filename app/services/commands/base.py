"""What every slash command module shares: the reply kinds, the services, and
the readers of a payload. The command modules import this, never
app.services.interactions, which imports them."""

from math import ceil
from typing import Any, NamedTuple

from app.core.query import QueryUtil
from app.models.season import SeasonPublic
from app.models.series import SeriesPublic
from app.models.series_cast import channel_name
from app.models.team import TeamReduced
from app.models.types import utcnow
from app.models.user import UserPublic
from app.services import discord_roles
from app.services.fantasy_teams import FantasyTeamService
from app.services.ladder import LadderService
from app.services.seasons import SeasonService
from app.services.series import SeriesService
from app.services.users import UserService

# A reply is public in the channel, or a private edit of the deferred "thinking" reply
PUBLIC, PRIVATE = True, False


class Services(NamedTuple):
    """What the commands read and write through."""

    series: SeriesService
    users: UserService
    ladder: LadderService
    seasons: SeasonService
    fantasy: FantasyTeamService


def options_of(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        option["name"]: option["value"]
        for option in payload.get("data", {}).get("options", [])
    }


def caller(payload: dict[str, Any]) -> tuple[str, str]:
    """The Discord id and display name of the member who sent the interaction."""
    user = payload.get("member", {}).get("user") or payload.get("user", {})
    return str(user.get("id")), user.get("global_name") or user.get("username") or "?"


def typed_option(payload: dict[str, Any]) -> str:
    """What the member has typed so far in the option he is filling, lowercased."""
    return next(
        (
            str(option.get("value", "")).lower()
            for option in payload.get("data", {}).get("options", [])
            if option.get("focused")
        ),
        "",
    )


def series_line(series: SeriesPublic) -> str:
    def side(player: UserPublic | None, team: TeamReduced | None) -> str:
        name = (player.name if player else None) or "?"
        return f"{name} ({team.name})" if team else name

    match = series.match
    stamp = f"<t:{int(series.date_time.timestamp())}:f>" if series.date_time else "TBD"
    line = f"{stamp} · Wk {match.playday if match else '?'} · "
    line += side(series.player1, match.team1 if match else None)
    line += " vs " + side(series.player2, match.team2 if match else None)
    for cast in series.casts:
        line += f" · {channel_name(cast.channel_url)}"
    return line + f" · #{series.id}"


def own_series(payload: dict[str, Any], services: Services) -> list[SeriesPublic]:
    """The caller's series of the current season, soonest first."""
    discord_id, _ = caller(payload)
    users = services.users.find_by_discord_id(discord_id)
    season_id = discord_roles.current_season()
    if not users or season_id is None:
        return []
    query = f"player1_id == {users[0].id} or player2_id == {users[0].id}"
    return services.series.search_for_season(
        season_id, QueryUtil.parse_query(query), sort="date_time"
    )


def season_span(season: SeasonPublic) -> str:
    """The season's date range and the calendar week of it today sits in.

    The weeks are the range's, as the achievement window counts them, not the
    play weeks: a review season can span more weeks than it plays.
    """
    start, end = season.start_date, season.end_date
    span = f"{start or '?'} to {end or '?'}"
    today = utcnow().date()
    if start is None or today < start:
        return span
    if end is not None and today > end:
        return f"{span} · ended"
    week = (today - start).days // 7 + 1
    if end is None:
        return f"{span} · week {week}"
    return f"{span} · week {week} of {ceil(((end - start).days + 1) / 7)}"
