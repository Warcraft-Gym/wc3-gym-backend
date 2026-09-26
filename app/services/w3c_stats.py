"""The live ladder summary of a player: one row per race over the W3C window.

The window is the current W3C season (`w3c_season`) and the one before it.
Eligibility, ratings and fantasy read the window alone; a profile read may also
show a race with no window row from its newest older row, flagged stale.
"""

from collections.abc import Collection, Iterable
from typing import Any

from sqlalchemy import ColumnElement, ColumnExpressionArgument, func, select
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import aliased
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
    newest first, ties by race name. The main race is the window race with the top mmr among
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
    live.sort(
        key=lambda row: (-(row.mmr if row.mmr is not None else -1), row.race or "")
    )
    old.sort(key=lambda row: (-row.wc3_season, row.race or ""))
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


def summaries(
    session: OrmSession, user_ids: Collection[int], current: int, stale: bool = False
) -> dict[int, tuple[list[RaceMmr], str | None]]:
    """The summary of each user, from one row per race the database reduces.

    One statement reads the window; `stale` adds one for the races with no
    window row. A user with no row is left out.
    """
    if not user_ids:
        return {}
    season = col(W3CStats.wc3_season)
    by_race = (col(W3CStats.user_id), col(W3CStats.race))
    rows = _newest_per_race(
        session,
        in_window(current),
        func.sum(func.coalesce(col(W3CStats.games), 0))
        .over(partition_by=by_race)
        .label("games"),
        (col(W3CStats.mmr).is_not(None).desc(), season.desc()),
        user_ids,
    )
    if stale:
        live = aliased(W3CStats)
        rows += _newest_per_race(
            session,
            (season < current - 1)
            & ~select(col(live.id))
            .where(
                col(live.user_id) == col(W3CStats.user_id),
                col(live.race).is_not_distinct_from(col(W3CStats.race)),
                col(live.wc3_season).in_(window(current)),
            )
            .exists(),
            col(W3CStats.games).label("games"),
            (season.desc(),),
            user_ids,
        )
    by_user: dict[int, list[W3CStatsPublic]] = {}
    for row in rows:
        by_user.setdefault(row.user_id, []).append(row)
    return {
        user_id: summarize(stats, current, stale) for user_id, stats in by_user.items()
    }


def _newest_per_race(
    session: OrmSession,
    where: ColumnElement[bool],
    games: ColumnElement[Any],
    order: tuple[ColumnExpressionArgument[Any], ...],
    user_ids: Collection[int],
) -> list[W3CStatsPublic]:
    """The first row by `order` of each user and race, carrying `games` as its games."""
    ranked = (
        select(
            col(W3CStats.id),
            col(W3CStats.user_id),
            col(W3CStats.race),
            col(W3CStats.wc3_season),
            col(W3CStats.mmr),
            col(W3CStats.wins),
            col(W3CStats.losses),
            games,
            func.row_number()
            .over(
                partition_by=(col(W3CStats.user_id), col(W3CStats.race)),
                order_by=order,
            )
            .label("rank"),
        )
        .where(col(W3CStats.user_id).in_(user_ids), where)
        .subquery()
    )
    statement = select(ranked).where(ranked.c.rank == 1)
    return [
        W3CStatsPublic.model_validate(row)
        for row in session.execute(statement).mappings()
    ]


def fill(
    session: OrmSession,
    users: Iterable[UserListPublic | None],
    current: int,
    stale: bool = False,
) -> None:
    """The summary of every user, read in one statement, two with `stale`."""
    present = [user for user in users if user is not None]
    found = summaries(session, {user.id for user in present}, current, stale)
    for user in present:
        user.race_mmrs, user.main_race = found.get(user.id) or ([], None)
