import logging
from collections.abc import Iterable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core.db import Session
from app.core.exceptions import BadRequestError, NotFoundError
from app.models.base import ident
from app.models.draft_series import (
    DraftSeries,
    DraftSeriesCreate,
    DraftSeriesPublic,
    DraftSeriesUpdate,
)
from app.models.series import Series, SeriesCreate
from app.models.series_side import SeriesSide
from app.services import derived

logger = logging.getLogger(__name__)


def drafted_players(
    session: OrmSession, match_id: int, skip_series_id: int | None = None
) -> set[int]:
    """Every player the drafted series of one fixture already name.

    A drafted 1v1 names its player in the series columns; a drafted 2v2 names
    its side in `series_side`, so both are read.
    """
    rows = [
        row
        for row in session.scalars(
            select(Series).where(
                col(Series.match_id) == match_id,
                col(Series.pick_rule) == "drafted",
            )
        )
        if ident(row) != skip_series_id
    ]
    named = {
        player
        for row in rows
        for player in (row.player1_id, row.player2_id)
        if player is not None
    }
    if rows:
        named |= {
            side.user_id
            for side in session.scalars(
                select(SeriesSide).where(
                    col(SeriesSide.series_id).in_([ident(row) for row in rows])
                )
            )
            if side.user_id
        }
    return named


def refuse_repeat(
    session: OrmSession,
    match_id: int | None,
    players: Iterable[int | None],
    skip_series_id: int | None = None,
) -> None:
    """Refuse a drafted pick naming a player a sibling drafted series holds."""
    if match_id is None:
        return
    picked = {player for player in players if player is not None}
    if picked & drafted_players(session, match_id, skip_series_id):
        raise BadRequestError(
            "That player already plays a drafted series of this fixture"
        )


class DraftSeriesService:
    def add(self, draft_series: DraftSeriesCreate) -> DraftSeriesPublic:
        with Session.begin() as session:
            row = DraftSeries.add(session, draft_series.model_dump())
            public = DraftSeriesPublic.from_draft_series(row)
            derived.fill_signup_races(session, [public])
            return public

    def update(
        self, draft_series_id: int, draft_series: DraftSeriesUpdate
    ) -> DraftSeriesPublic:
        with Session.begin() as session:
            row = DraftSeries.update(
                session,
                draft_series_id,
                **draft_series.model_dump(exclude_unset=True),
            )
            if not row:
                raise NotFoundError("Draft series not found")
            public = DraftSeriesPublic.from_draft_series(row)
            derived.fill_signup_races(session, [public])
            return public

    def delete(self, draft_series_id: int) -> None:
        with Session.begin() as session:
            DraftSeries.delete(session, draft_series_id)

    def get(self, draft_series_id: int) -> DraftSeriesPublic:
        with Session.begin() as session:
            draft_series = session.scalars(
                select(DraftSeries)
                .options(*DraftSeries._eager_options())
                .where(col(DraftSeries.id) == draft_series_id)
            ).first()
            if not draft_series:
                raise NotFoundError("Draft series not found")
            public = DraftSeriesPublic.from_draft_series(draft_series)
            derived.fill_signup_races(session, [public])
            return public

    def get_by_match_id(
        self, match_id: int, limit: int | None = None, offset: int = 0
    ) -> list[DraftSeriesPublic]:
        with Session.begin() as session:
            # Offset paging is deterministic only with a fixed order
            statement = (
                select(DraftSeries)
                .options(*DraftSeries._eager_options())
                .where(col(DraftSeries.match_id) == match_id)
                .order_by(col(DraftSeries.id))
                .offset(offset)
                .limit(limit)
            )
            result = [
                DraftSeriesPublic.from_draft_series(row)
                for row in session.scalars(statement).all()
            ]
            derived.fill_signup_races(session, result)
            return result

    def delete_by_match_id(self, match_id: int) -> None:
        """Delete all draft series for a given match"""
        with Session.begin() as session:
            session.execute(
                delete(DraftSeries).where(col(DraftSeries.match_id) == match_id)
            )

    def convert_to_series(self, draft_series_id: int) -> SeriesCreate:
        """Build the SeriesCreate for a draft series. SeriesService writes the row."""
        with Session.begin() as session:
            draft_series = session.get(DraftSeries, draft_series_id)
            if not draft_series:
                raise NotFoundError("Draft series not found")
            return SeriesCreate(
                match_id=draft_series.match_id,
                date_time=draft_series.date_time,
                player1_id=draft_series.player1_id,
                player2_id=draft_series.player2_id,
                player1_score=draft_series.player1_score,
                player2_score=draft_series.player2_score,
                host_player_id=draft_series.host_player_id,
                is_fantasy_match=draft_series.is_fantasy_match,
            )
