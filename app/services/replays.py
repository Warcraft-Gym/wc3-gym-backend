"""The replays of a series: one file per game in Vercel Blob, one row per slot."""

from sqlmodel import col, select

from app.core.db import Session
from app.core.exceptions import NotFoundError
from app.models.match import Match
from app.models.series import Series
from app.models.series_replay import DBSeriesReplay, SeriesReplayPublic
from app.models.types import utcnow
from app.services import blob


def store(
    series_id: int, user_id: int | None, files: dict[str, bytes]
) -> list[SeriesReplayPublic]:
    """Put each game's replay in the store, then point its slot at it and drop the one it
    replaced. `files` is keyed game1, game2, game3."""
    # the store is not part of the transaction, so the put happens first: a put that is never
    # committed leaves an unreferenced blob, while a committed row must point at a written one
    urls = {
        int(key[-1]): blob.put_replay(f"replays/{series_id}/{key}", data)
        for key, data in files.items()
    }
    replaced: list[str] = []
    with Session.begin() as session:
        for game_no, url in urls.items():
            # locked: two uploads for one slot would otherwise both read the same previous URL
            row = session.get(
                DBSeriesReplay, (series_id, game_no), with_for_update=True
            )
            if row:
                replaced.append(row.url)
                row.url, row.uploaded_by, row.uploaded_at = url, user_id, utcnow()
            else:
                session.add(
                    DBSeriesReplay(
                        series_id=series_id,
                        game_no=game_no,
                        url=url,
                        uploaded_by=user_id,
                    )
                )
        session.flush()
        rows = session.scalars(
            select(DBSeriesReplay)
            .where(col(DBSeriesReplay.series_id) == series_id)
            .order_by(col(DBSeriesReplay.game_no))
        )
        public = [SeriesReplayPublic.model_validate(row) for row in rows]
    for url in replaced:
        blob.delete_blob(url)
    return public


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
        return [SeriesReplayPublic.model_validate(row) for row in rows]
