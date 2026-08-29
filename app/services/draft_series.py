import logging

from sqlalchemy import delete, select
from sqlmodel import col

from app.core.db import Session
from app.core.exceptions import NotFoundError
from app.models.draft_series import (
    DraftSeries,
    DraftSeriesCreate,
    DraftSeriesPublic,
    DraftSeriesUpdate,
)
from app.models.series import SeriesCreate

logger = logging.getLogger(__name__)


class DraftSeriesService:
    def add(self, draft_series: DraftSeriesCreate) -> DraftSeriesPublic:
        with Session.begin() as session:
            row = DraftSeries.add(session, draft_series.model_dump())
            return DraftSeriesPublic.from_draft_series(row)

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
            return DraftSeriesPublic.from_draft_series(row)

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
            return DraftSeriesPublic.from_draft_series(draft_series)

    def get_by_match_id(
        self, match_id: int, limit: int | None = None, offset: int = 0
    ) -> list[DraftSeriesPublic]:
        with Session.begin() as session:
            result = []
            statement = (
                select(DraftSeries)
                .options(*DraftSeries._eager_options())
                .where(col(DraftSeries.match_id) == match_id)
            )
            if limit is not None or offset:
                # Offset paging is deterministic only with a fixed order
                statement = statement.order_by(col(DraftSeries.id)).offset(offset)
                if limit is not None:
                    statement = statement.limit(limit)
            draft_series_list = session.scalars(statement).all()
            for single_draft_series in draft_series_list:
                result.append(DraftSeriesPublic.from_draft_series(single_draft_series))
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
                caster=draft_series.caster,
                player1_id=draft_series.player1_id,
                player2_id=draft_series.player2_id,
                player1_score=draft_series.player1_score or 0,
                player2_score=draft_series.player2_score or 0,
                host_player_id=draft_series.host_player_id,
                is_fantasy_match=draft_series.is_fantasy_match,
            )
