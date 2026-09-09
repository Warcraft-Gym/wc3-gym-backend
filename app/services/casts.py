"""The casts of a series: who streams it, on which channel.

Any member claims a series once. The owner of a claim, or an admin, changes
its channel or removes it. A cast the importer wrote has no owner, so only
an admin touches it.
"""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col, select

from app.core.db import Session
from app.models.base import ident
from app.core.exceptions import ApiError, BadRequestError, NotFoundError
from app.models.series import Series, SeriesPublic, has_result
from app.models.series_cast import CastPublic, SeriesCast, is_video_url
from app.models.types import utcnow
from app.services import discord_posts

# A cast series counts as on now from half an hour before its time to four hours after
WINDOW_BEFORE = timedelta(minutes=30)
WINDOW_AFTER = timedelta(hours=4)

# How far back last_channel looks for a channel that is not a one-off video URL
LAST_CLAIMS = 10

# The reminder goes out this far before the start. The job behind it runs every
# few minutes, so the audience sees the card about ten minutes before the games.
REMINDER_LEAD = timedelta(minutes=15)
# A scheduled run can be late; a series that started this recently still gets its card
REMINDER_LATE = timedelta(minutes=30)


def starting_soon(now: datetime) -> list[int]:
    """The claimed series about to start and not yet played, soonest first."""
    with Session() as session:
        rows = session.scalars(
            select(Series)
            .where(
                col(Series.id).in_(select(col(SeriesCast.series_id))),
                col(Series.date_time) >= now - REMINDER_LATE,
                col(Series.date_time) <= now + REMINDER_LEAD,
                col(Series.player1_score).is_(None),
                col(Series.player2_score).is_(None),
            )
            .order_by(col(Series.date_time))
        )
        return [ident(row) for row in rows]


def on_now(series: SeriesPublic, now: datetime) -> bool:
    """A claimed series with no result, inside its window. No platform is asked."""
    if not series.casts or series.date_time is None:
        return False
    if has_result(series):
        return False
    return series.date_time - WINDOW_BEFORE <= now <= series.date_time + WINDOW_AFTER


def _rows(session: OrmSession, series_id: int) -> list[CastPublic]:
    series = session.get(Series, series_id)
    scored = has_result(series) if series else False
    rows = session.scalars(
        select(SeriesCast)
        .where(col(SeriesCast.series_id) == series_id)
        .order_by(col(SeriesCast.id))
    )
    return [CastPublic.from_cast(row, scored) for row in rows]


def _owned(
    session: OrmSession, series_id: int, cast_id: int, user_id: int, admin: bool
) -> SeriesCast:
    row = session.get(SeriesCast, cast_id)
    if not row or row.series_id != series_id:
        raise NotFoundError("Cast not found")
    if not admin and row.user_id != user_id:
        raise ApiError(403, {"error": "Only the caster or an admin edits a cast"})
    return row


def for_series(series_id: int) -> list[CastPublic]:
    with Session() as session:
        if not session.get(Series, series_id):
            raise NotFoundError("Series not found")
        return _rows(session, series_id)


def claim(
    series_id: int, user_id: int, channel_url: str, vod_url: str | None = None
) -> list[CastPublic]:
    """Add the account's claim; the account claims a series once.

    A series with a result has nothing left to stream, so it is claimed with a VOD.
    """
    with Session.begin() as session:
        series = session.get(Series, series_id)
        if not series:
            raise NotFoundError("Series not found")
        if not vod_url and has_result(series):
            raise BadRequestError("This series is over; a VOD link is needed")
        taken = session.scalar(
            select(SeriesCast.id).where(
                col(SeriesCast.series_id) == series_id,
                col(SeriesCast.user_id) == user_id,
            )
        )
        if taken:
            raise BadRequestError("You already cast this series")
        session.add(
            SeriesCast(
                series_id=series_id,
                user_id=user_id,
                channel_url=channel_url,
                vod_url=vod_url,
                vod_added_at=utcnow() if vod_url else None,
            )
        )
        session.flush()
        rows = _rows(session, series_id)
        over = has_result(series)
    # A series that is over is claimed for its VOD alone: there is nothing to announce
    if not over:
        discord_posts.post_cast(series_id)
    return rows


def update(
    series_id: int, cast_id: int, user_id: int, admin: bool, channel_url: str
) -> list[CastPublic]:
    with Session.begin() as session:
        row = _owned(session, series_id, cast_id, user_id, admin)
        row.channel_url = channel_url
        session.flush()
        return _rows(session, series_id)


def set_vod(
    series_id: int, cast_id: int, user_id: int, admin: bool, vod_url: str | None
) -> list[CastPublic]:
    """Paste, replace or clear the VOD. When it was added is kept: a Twitch VOD expires."""
    with Session.begin() as session:
        row = _owned(session, series_id, cast_id, user_id, admin)
        row.vod_url = vod_url
        row.vod_added_at = utcnow() if vod_url else None
        session.flush()
        return _rows(session, series_id)


def unclaim(series_id: int, cast_id: int, user_id: int, admin: bool) -> None:
    with Session.begin() as session:
        session.delete(_owned(session, series_id, cast_id, user_id, admin))


def last_channel(user_id: int) -> str | None:
    """The channel of the account's newest claim, to pre-fill the next one.

    A video URL is one stream, not a channel, so it pre-fills nothing: a YouTube
    caster's last claim carries that stream's watch URL, which the next series
    must not reuse.
    """
    with Session() as session:
        urls = session.scalars(
            select(SeriesCast.channel_url)
            .where(col(SeriesCast.user_id) == user_id)
            .order_by(col(SeriesCast.id).desc())
            .limit(LAST_CLAIMS)
        )
        return next((url for url in urls if not is_video_url(url)), None)
