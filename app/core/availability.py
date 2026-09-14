"""What the check-in shows one player for one round. Reads only, writes nothing.

The player's own answer is the truth. With no answer, their soft blocks say
whether the whole round window is covered, which the page shows as a hint with
one button to confirm: blocks inform, they never constrain.
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core import free_time
from app.models.base import ident
from app.models.relationships import DBEventRound
from app.models.round_availability import DBRoundAvailability
from app.models.season import AvailabilityHint
from app.models.user import User
from app.models.user_block import UserBlock, UserBusy


def blocked(
    session: OrmSession, user_id: int, start: datetime, end: datetime
) -> list[free_time.Interval]:
    """The UTC intervals one player blocked inside [start, end)."""
    zone = session.scalar(select(col(User.timezone)).where(col(User.id) == user_id))
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
    """The hint for one player and one round, from their answer or their blocks.

    A round with no dates and a player with no zone are both open: blank means
    open, so nothing here refuses anyone.
    """
    answer = session.get(
        DBRoundAvailability, (ident(user), round_.season_id, round_.number)
    )
    if answer is not None:
        return "answered_yes" if answer.available else "answered_no"
    if round_.start_date is None or not user.timezone:
        return "open"
    zone = ZoneInfo(user.timezone)
    start = free_time.instant(round_.start_date, time(), zone)
    end = free_time.instant(
        (round_.end_date or round_.start_date) + timedelta(days=1), time(), zone
    )
    spans = blocked(session, ident(user), start, end)
    return "open" if free_time.free(start, end, spans) else "blocked_by_blocks"
