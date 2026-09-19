"""What the check-in shows one player for one round. Reads only, writes nothing.

The player's own answer is the truth. With no answer, their soft blocks say
whether the whole round window is covered, which the page shows as a hint with
one button to confirm: blocks inform, they never constrain.
"""

from collections.abc import Collection, Iterable, Mapping
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core import free_time
from app.models.base import ident
from app.models.relationships import DBEventRound
from app.models.round_availability import DBRoundAvailability
from app.models.season import AvailabilityHint, Season
from app.models.user import User
from app.models.user_block import UserBlock, UserBusy


def round_window(
    event: Season, round_: DBEventRound | None, zone: str | None = None
) -> tuple[datetime, datetime] | None:
    """The instants one round runs between, midnight to midnight after its last day.

    The event's `round_end_zone` names the zone, else the caller's fallback,
    else UTC. A round with no dates falls back to the event's own dates, and an
    event with none has no window.
    """
    first = round_.start_date if round_ is not None else None
    last = (round_.end_date or first) if round_ is not None else None
    if first is None:
        first, last = event.start_date, event.end_date or event.start_date
    if first is None:
        return None
    named = ZoneInfo(event.round_end_zone or zone or "UTC")
    return (
        free_time.instant(first, time(), named),
        free_time.instant((last or first) + timedelta(days=1), time(), named),
    )


def blocked_rounds(
    session: OrmSession,
    event: Season,
    user_ids: Collection[int],
    rounds: Iterable[DBEventRound],
) -> set[tuple[int, int]]:
    """The (player, round number) pairs whose blocks cover a whole round window.

    The round window stands in the event's zone and each player's blocks in
    their own, so a player in another zone still reads against the event's
    round. Three statements answer the whole list, never one per pair.
    """
    dated = [round_ for round_ in rounds if round_.start_date is not None]
    if not user_ids or not dated:
        return set()
    zones = {
        user_id: zone
        for user_id, zone in session.execute(
            select(col(User.id), col(User.timezone)).where(col(User.id).in_(user_ids))
        ).all()
    }
    windows = {
        (user_id, round_.number): window
        for user_id in user_ids
        if zones.get(user_id)
        for round_ in dated
        if (window := round_window(event, round_, zones[user_id])) is not None
    }
    if not windows:
        return set()
    blocks: dict[int, list[UserBlock]] = {}
    for block in session.scalars(
        select(UserBlock).where(col(UserBlock.user_id).in_(user_ids))
    ):
        blocks.setdefault(block.user_id, []).append(block)
    # A local last day can sit a calendar day behind the earliest window start
    first = min(start for start, _ in windows.values()).date() - timedelta(days=1)
    busy: dict[int, list[UserBusy]] = {}
    for day in session.scalars(
        select(UserBusy).where(
            col(UserBusy.user_id).in_(user_ids), col(UserBusy.last_day) >= first
        )
    ):
        busy.setdefault(day.user_id, []).append(day)
    return {
        (user_id, number)
        for (user_id, number), (start, end) in windows.items()
        if not free_time.free(
            start,
            end,
            free_time.blocked(
                zones[user_id],
                blocks.get(user_id, []),
                busy.get(user_id, []),
                start,
                end,
            ),
        )
    }


def zone_of(session: OrmSession, user_id: int) -> str | None:
    """The timezone one player set; blank means open."""
    return session.scalar(select(col(User.timezone)).where(col(User.id) == user_id))


def blocked(
    session: OrmSession,
    user_id: int,
    start: datetime,
    end: datetime,
    zone: str | None,
) -> list[free_time.Interval]:
    """The UTC intervals one player blocked inside [start, end).

    The caller passes the player's timezone, so a caller that already holds it
    reads it once rather than once per window.
    """
    blocks = session.scalars(select(UserBlock).where(col(UserBlock.user_id) == user_id))
    # A local last day can sit a calendar day behind the UTC window start
    busy = session.scalars(
        select(UserBusy).where(
            col(UserBusy.user_id) == user_id,
            col(UserBusy.last_day) >= start.date() - timedelta(days=1),
        )
    )
    return free_time.blocked(zone, blocks, busy, start, end)


def availability_hint(
    session: OrmSession, user: User, round_: DBEventRound
) -> AvailabilityHint:
    """The hint for one player and one round, from their answer or their blocks."""
    return availability_hints(session, user, {0: round_})[0]


def availability_hints(
    session: OrmSession, user: User, rounds: Mapping[int, DBEventRound]
) -> dict[int, AvailabilityHint]:
    """The hint for one player over several rounds, keyed as the caller keys them.

    A round with no dates and a player with no zone are both open: blank means
    open, so nothing here refuses anyone. Every round of the same player reads
    the same blocks and busy days, so they are read once for the whole list.
    The round window stands in the event's zone, the blocks in the player's.
    """
    answers = _answers(session, ident(user), rounds.values())
    zone_name = user.timezone
    hints: dict[int, AvailabilityHint] = {}
    windows: dict[int, tuple[datetime, datetime]] = {}
    for key, round_ in rounds.items():
        answer = answers.get((round_.season_id, round_.number))
        if answer is not None:
            hints[key] = "answered_yes" if answer else "answered_no"
        elif round_.start_date is None or not zone_name:
            hints[key] = "open"
        else:
            window = round_window(round_.season, round_, zone_name)
            if window is None:
                hints[key] = "open"
            else:
                windows[key] = window
    if not windows or not zone_name:
        return hints
    blocks = list(
        session.scalars(select(UserBlock).where(col(UserBlock.user_id) == ident(user)))
    )
    # A local last day can sit a calendar day behind the earliest window start
    busy = list(
        session.scalars(
            select(UserBusy).where(
                col(UserBusy.user_id) == ident(user),
                col(UserBusy.last_day)
                >= min(start for start, _ in windows.values()).date()
                - timedelta(days=1),
            )
        )
    )
    for key, (start, end) in windows.items():
        spans = free_time.blocked(zone_name, blocks, busy, start, end)
        hints[key] = (
            "open" if free_time.free(start, end, spans) else "blocked_by_blocks"
        )
    return hints


def _answers(
    session: OrmSession, user_id: int, rounds: Iterable[DBEventRound]
) -> dict[tuple[int, int], bool]:
    """Whether the player answered each of those rounds, in one statement."""
    wanted = {(round_.season_id, round_.number) for round_ in rounds}
    if not wanted:
        return {}
    rows = session.scalars(
        select(DBRoundAvailability).where(
            col(DBRoundAvailability.user_id) == user_id,
            col(DBRoundAvailability.season_id).in_({key[0] for key in wanted}),
        )
    )
    return {
        (row.season_id, row.playday): row.available
        for row in rows
        if (row.season_id, row.playday) in wanted
    }
