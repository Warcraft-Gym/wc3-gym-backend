"""The replays of a series: one file per game in the R2 bucket, one row per slot."""

from sqlmodel import col, select

from app.core.db import Session
from app.core.exceptions import BadRequestError, NotFoundError
from app.models.match import Match
from app.models.series import Series
from app.models.series_replay import DBSeriesReplay, SeriesReplayPublic
from app.models.types import utcnow
from app.services import r2

REPLAY_MAGIC = b"Warcraft III recorded game\x1a\x00"
MAX_REPLAY_BYTES = 4 * 1024 * 1024


def replay_check(data: bytes) -> None:
    """Refuse anything that is not a Warcraft III replay, before it is stored."""
    if not data.startswith(REPLAY_MAGIC):
        raise BadRequestError("Not a Warcraft III replay")
    if len(data) > MAX_REPLAY_BYTES:
        raise BadRequestError(f"Replay is larger than {MAX_REPLAY_BYTES // 1024} KB")


def public(row: DBSeriesReplay) -> SeriesReplayPublic:
    """The row with a fresh download link in place of its key."""
    return SeriesReplayPublic(
        series_id=row.series_id,
        game_no=row.game_no,
        url=r2.download_url(row.key),
        uploaded_by=row.uploaded_by,
        uploaded_at=row.uploaded_at,
    )


def store(
    series_id: int, user_id: int | None, files: dict[str, bytes]
) -> list[SeriesReplayPublic]:
    """Put each game's replay in the store over the one it replaces, then point its slot at it.
    `files` is keyed game1, game2, game3."""
    # the store is not part of the transaction, so the put happens first: a put that is never
    # committed is overwritten by the next report, while a committed row must point at a written
    # file
    keys = {int(name[-1]): r2.key(series_id, int(name[-1])) for name in files}
    for name, data in files.items():
        r2.put(keys[int(name[-1])], data)
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
