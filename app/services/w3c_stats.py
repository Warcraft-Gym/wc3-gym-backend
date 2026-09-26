"""The live ladder summary of a player: one row per race over the W3C window.

The window is the current W3C season (`w3c_season`) and the one before it.
Eligibility, ratings and fantasy read the window alone; a profile read may also
show a race with no window row from its newest older row, flagged stale.
"""

from collections.abc import Iterable

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.models.settings import Settings
from app.models.user import UserListPublic
from app.models.w3c_stats import RaceMmr, W3CStats, W3CStatsPublic

# The setting that names the W3C season the app is on
W3C_SEASON_KEY = "current_w3c_season"

# A race is the main race with this many games in the window
MAIN_RACE_GAMES = 10


def w3c_season(session: OrmSession) -> int:
    """The W3C season the app reads ratings against, or the newest one stored."""
    named = session.scalar(
        select(col(Settings.value)).where(col(Settings.key) == W3C_SEASON_KEY)
    )
    if named:
        return int(named)
    return session.scalar(select(func.max(col(W3CStats.wc3_season)))) or 0


def window(current: int) -> tuple[int, int]:
    """The W3C seasons of the live window."""
    return current - 1, current


def in_window(current: int) -> ColumnElement[bool]:
    """The w3cstats rows of the live window, for a where clause or a loader."""
    return col(W3CStats.wc3_season).in_(window(current))


def summarize(
    rows: Iterable[W3CStatsPublic], current: int, stale: bool = False
) -> tuple[list[RaceMmr], str | None]:
    """The races of one player, and his main race.

    A race with window rows answers the mmr and record of its newest window
    row with a rating, else its newest window row, and the games of every
    window row; with `stale`, a race with none answers its
    newest older row, flagged. Window races come first by mmr, then stale races
    newest first. The main race is the window race with the top mmr among
    those with MAIN_RACE_GAMES games, else None.
    """
    by_race: dict[str | None, list[W3CStatsPublic]] = {}
    for row in rows:
        by_race.setdefault(row.race, []).append(row)
    live: list[RaceMmr] = []
    old: list[RaceMmr] = []
    for race, stats in by_race.items():
        inside = [row for row in stats if row.wc3_season in window(current)]
        older = [row for row in stats if row.wc3_season < current - 1]
        if inside:
            rated = [row for row in inside if row.mmr is not None] or inside
            newest = max(rated, key=lambda row: row.wc3_season)
            games = sum(row.games or 0 for row in inside)
            live.append(_race_mmr(race, newest, games, stale=False))
        elif stale and older:
            newest = max(older, key=lambda row: row.wc3_season)
            old.append(_race_mmr(race, newest, newest.games, stale=True))
    live.sort(key=lambda row: row.mmr if row.mmr is not None else -1, reverse=True)
    old.sort(key=lambda row: row.wc3_season, reverse=True)
    main = next(
        (
            row.race
            for row in live
            if row.mmr is not None and (row.games or 0) >= MAIN_RACE_GAMES
        ),
        None,
    )
    return live + old, main


def _race_mmr(
    race: str | None, row: W3CStatsPublic, games: int | None, stale: bool
) -> RaceMmr:
    return RaceMmr(
        race=race,
        wc3_season=row.wc3_season,
        mmr=row.mmr,
        games=games,
        wins=row.wins,
        losses=row.losses,
        stale=stale,
    )


def fill(
    users: Iterable[UserListPublic | None], current: int, stale: bool = False
) -> None:
    """The summary of every user, from the w3c_stats rows the read loaded."""
    for user in users:
        if user is not None:
            user.race_mmrs, user.main_race = summarize(user.w3c_stats, current, stale)
