"""Every fixture and series names the round it is played in.

The rows are written from six places: the match and series services, the
season import, the review season builder and the seed. The round is resolved
once here, on the session, so a fixture written after the C1 backfill carries
its round id the same way a migrated one does. One query per flush covers
every row in it. app.core.db registers the listener.
"""

from sqlalchemy import event, select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core.db import Session
from app.models.match import Match
from app.models.relationships import DBEventRound
from app.models.series import Series


def _fixture(session: OrmSession, row: Match | Series) -> Match | None:
    """The fixture a row is played in: itself, or the one the series names."""
    if isinstance(row, Match):
        return row
    return session.get(Match, row.match_id) if row.match_id else None


@event.listens_for(Session, "before_flush")
def _set_round(session: OrmSession, *_: object) -> None:
    """Fill round_id from (season_id, playday) before the row is written.

    A playday with no round leaves the column as it is; C2 makes it required.
    """
    rows = [
        row for row in (*session.new, *session.dirty) if isinstance(row, Match | Series)
    ]
    if not rows:
        return
    with session.no_autoflush:
        wanted: list[tuple[Match | Series, tuple[int, int]]] = []
        for row in rows:
            fixture = _fixture(session, row)
            if fixture is not None:
                wanted.append((row, (fixture.season_id, fixture.playday)))
        if not wanted:
            return
        found = {
            (round_.season_id, round_.number): round_.id
            for round_ in session.scalars(
                select(DBEventRound).where(
                    col(DBEventRound.season_id).in_(
                        {season_id for _, (season_id, _) in wanted}
                    )
                )
            )
        }
    for row, key in wanted:
        round_id = found.get(key)
        if round_id is not None and row.round_id != round_id:
            row.round_id = round_id
