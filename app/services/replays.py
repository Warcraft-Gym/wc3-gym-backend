"""The replays of a series: one file per game in the R2 bucket, one row per slot.

The browser uploads each file to the bucket itself, at a link this module signs. A slot is
written only once the file is there and starts like a replay, so a row never points at
nothing. A re-upload lands on the same key, so nothing is deleted.
"""

from collections.abc import Iterable

from sqlmodel import col, select

from app.core.db import Session
from app.core.exceptions import BadRequestError, NotFoundError
from app.models.match import Match
from app.models.series import Series
from app.models.series_replay import DBSeriesReplay, SeriesReplayPublic
from app.models.types import utcnow
from app.services import r2

REPLAY_MAGIC = b"Warcraft III recorded game\x1a\x00"


def upload_url(series_id: int, game_no: int) -> str:
    """Where the browser puts one game's replay."""
    return r2.upload_url(r2.key(series_id, game_no))


def public(row: DBSeriesReplay) -> SeriesReplayPublic:
    """The row with a fresh download link in place of its key."""
    return SeriesReplayPublic(
        series_id=row.series_id,
        game_no=row.game_no,
        url=r2.download_url(row.key),
        uploaded_by=row.uploaded_by,
        uploaded_at=row.uploaded_at,
    )


def confirm(
    series_id: int, games: Iterable[int], user_id: int | None
) -> list[SeriesReplayPublic]:
    """Point each game's slot at the file the browser uploaded. Every file is checked before
    any slot is written, so a report with one file missing changes nothing."""
    keys = {game_no: r2.key(series_id, game_no) for game_no in games}
    for game_no, key in keys.items():
        found = r2.peek(key)
        if not found:
            raise BadRequestError(f"Game {game_no} replay is missing")
        if not found[0].startswith(REPLAY_MAGIC):
            raise BadRequestError(f"Game {game_no} is not a Warcraft III replay")
    with Session.begin() as session:
        for game_no, key in keys.items():
            row = session.get(DBSeriesReplay, (series_id, game_no))
            if row:
                row.key, row.uploaded_by, row.uploaded_at = key, user_id, utcnow()
            else:
                session.add(
                    DBSeriesReplay(
                        series_id=series_id,
                        game_no=game_no,
                        key=key,
                        uploaded_by=user_id,
                    )
                )
        session.flush()
        rows = session.scalars(
            select(DBSeriesReplay)
            .where(col(DBSeriesReplay.series_id) == series_id)
            .order_by(col(DBSeriesReplay.game_no))
        )
        return [public(row) for row in rows]


def for_match(match_id: int) -> list[SeriesReplayPublic]:
    """The replay of every game played in this match, in series and game order."""
    with Session() as session:
        if not session.get(Match, match_id):
            raise NotFoundError(f"Match not found by id: {match_id}")
        rows = session.scalars(
            select(DBSeriesReplay)
            .join(Series, col(Series.id) == col(DBSeriesReplay.series_id))
            .where(col(Series.match_id) == match_id)
            .order_by(col(DBSeriesReplay.series_id), col(DBSeriesReplay.game_no))
        )
        return [public(row) for row in rows]
