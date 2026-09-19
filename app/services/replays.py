"""The replays of a series: one file per game in the R2 bucket, one row per slot.

The browser uploads each file to the bucket itself, at a link this module signs. A slot is
written only once the file is there, starts like a replay and is under `MAX_BYTES`, so a row
never points at nothing. A re-upload lands on the same key, so nothing is deleted; an oversized
file is dropped from the bucket instead.
"""

from collections.abc import Iterable

from sqlmodel import col, select

from app.core.db import Session
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.scoring import wins_needed
from app.models.match import Match
from app.models.series import Series
from app.models.series_replay import DBSeriesReplay, SeriesReplayPublic
from app.models.types import utcnow
from app.services import r2

REPLAY_MAGIC = b"Warcraft III recorded game\x1a\x00"
# A real replay is a few hundred KB; the Discord path refuses the same size
MAX_BYTES = 10 * 1024 * 1024


def max_games(series_id: int) -> int:
    """The most games this series can hold: one short of twice the map wins its
    season needs, so a Bo3 tops out at 3."""
    with Session() as session:
        row = session.get(Series, series_id)
        season = row.match.season if row and row.match else None
        return 2 * wins_needed(season.map_rules if season else None) - 1


def upload_url(series_id: int, game_no: int) -> str:
    """Where the browser puts one game's replay. The season's best-of bounds the
    game number, so one series signs a bounded set of keys."""
    games = max_games(series_id)
    if not 1 <= game_no <= games:
        raise BadRequestError(f"Game number must be between 1 and {games}")
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
        if found[1] > MAX_BYTES:
            r2.delete(key)
            raise BadRequestError(f"Game {game_no} replay is over 10 MB")
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


def move(series_id: int, from_game: int, to_game: int) -> list[SeriesReplayPublic]:
    """Move one game's replay to another game of the same series; when that game holds a replay
    the two swap. The files change place in the bucket, so each game keeps its own key and the
    next upload to either game overwrites nothing else. The uploader and the time follow the file.
    """
    games = max_games(series_id)
    if from_game == to_game:
        raise BadRequestError("Pick a different game")
    for game_no in (from_game, to_game):
        if not 1 <= game_no <= games:
            raise BadRequestError(f"Game number must be between 1 and {games}")
    stale = None
    with Session.begin() as session:
        source = session.get(DBSeriesReplay, (series_id, from_game))
        if source is None:
            raise BadRequestError(f"Game {from_game} has no replay")
        target = session.get(DBSeriesReplay, (series_id, to_game))
        # what each game holds after the move, read before anything is written
        after = {
            to_game: (r2.fetch(source.key), source.uploaded_by, source.uploaded_at)
        }
        if target is not None:
            after[from_game] = (
                r2.fetch(target.key),
                target.uploaded_by,
                target.uploaded_at,
            )
        else:
            stale = source.key
            session.delete(source)
        for game_no, (data, by, at) in after.items():
            key = r2.key(series_id, game_no)
            r2.store(key, data)
            row = session.get(DBSeriesReplay, (series_id, game_no))
            if row is None:
                row = DBSeriesReplay(series_id=series_id, game_no=game_no, key=key)
                session.add(row)
            row.key, row.uploaded_by, row.uploaded_at = key, by, at
        session.flush()
        rows = session.scalars(
            select(DBSeriesReplay)
            .where(col(DBSeriesReplay.series_id) == series_id)
            .order_by(col(DBSeriesReplay.game_no))
        )
        answer = [public(row) for row in rows]
    # the file the row no longer points at goes after the commit, as a deleted series does
    if stale:
        r2.delete(stale)
    return answer


def for_series(series_id: int) -> list[SeriesReplayPublic]:
    """The replay of every game played in this series, in game order."""
    with Session() as session:
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
