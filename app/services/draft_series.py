import logging

from sqlalchemy import delete, select
from sqlalchemy.orm import joinedload

from app.exceptions import DBException, NotFoundException
from app.models.draft_series import DBDraftSeries
from app.models.match import DBMatch
from app.models.relationships import DBUserTeamSeason
from app.models.user import DBUser
from app.schemas.draft_series import DraftSeries
from app.schemas.series import Series
from app.services.base import BaseService

logger = logging.getLogger(__name__)


class DraftSeriesService(BaseService):
    def add(self, draft_series: DraftSeries):
        with self.get_session() as session:
            draft_series = DBDraftSeries.add(session, draft_series.to_db_dict())
            if not draft_series:
                raise DBException("Draft series could not be created!")
            return DraftSeries.from_db_draft_series(draft_series)

    def update(self, draft_series: DraftSeries):
        with self.get_session() as session:
            draft_series = DBDraftSeries.update(
                session, draft_series.id, **draft_series.to_db_dict()
            )
            if not draft_series:
                raise DBException("Draft series could not be updated!")
            return DraftSeries.from_db_draft_series(draft_series)

    def delete(self, draft_series_id):
        with self.get_session() as session:
            DBDraftSeries.delete(session, draft_series_id)

    def get(self, draft_series_id):
        with self.get_session() as session:
            # Eager load relationships to avoid N+1 queries
            draft_series = (
                session.scalars(
                    select(DBDraftSeries)
                    .options(
                        joinedload(DBDraftSeries.match).joinedload(DBMatch.team1),
                        joinedload(DBDraftSeries.match).joinedload(DBMatch.team2),
                        joinedload(DBDraftSeries.player1).joinedload(DBUser.w3c_stats),
                        joinedload(DBDraftSeries.player1)
                        .joinedload(DBUser.team_seasons)
                        .joinedload(DBUserTeamSeason.season),
                        joinedload(DBDraftSeries.player2).joinedload(DBUser.w3c_stats),
                        joinedload(DBDraftSeries.player2)
                        .joinedload(DBUser.team_seasons)
                        .joinedload(DBUserTeamSeason.season),
                    )
                    .where(DBDraftSeries.id == draft_series_id)
                )
                .unique()
                .first()
            )
            if not draft_series:
                raise DBException("Draft series could not be found")
            return DraftSeries.from_db_draft_series(draft_series)

    def getByMatchId(self, match_id):
        with self.get_session() as session:
            result = []
            # Eager load relationships
            draft_series_list = (
                session.scalars(
                    select(DBDraftSeries)
                    .options(
                        joinedload(DBDraftSeries.match).joinedload(DBMatch.team1),
                        joinedload(DBDraftSeries.match).joinedload(DBMatch.team2),
                        joinedload(DBDraftSeries.player1).joinedload(DBUser.w3c_stats),
                        joinedload(DBDraftSeries.player1)
                        .joinedload(DBUser.team_seasons)
                        .joinedload(DBUserTeamSeason.season),
                        joinedload(DBDraftSeries.player2).joinedload(DBUser.w3c_stats),
                        joinedload(DBDraftSeries.player2)
                        .joinedload(DBUser.team_seasons)
                        .joinedload(DBUserTeamSeason.season),
                    )
                    .where(DBDraftSeries.match_id == match_id)
                )
                .unique()
                .all()
            )
            for single_draft_series in draft_series_list:
                result.append(DraftSeries.from_db_draft_series(single_draft_series))
            return result

    def deleteByMatchId(self, match_id):
        """Delete all draft series for a given match"""
        with self.get_session() as session:
            session.execute(
                delete(DBDraftSeries).where(DBDraftSeries.match_id == match_id)
            )

    def create_draft_series(self, draft_series: DraftSeries):
        """Create a new draft series"""
        draft_series.id = None
        return self.add(draft_series)

    def update_draft_series(self, draft_series_id: int, draft_series: DraftSeries):
        """Update an existing draft series"""
        draft_series.id = draft_series_id
        return self.update(draft_series)

    def delete_draft_series(self, draft_series_id: int):
        """Delete a draft series"""
        self.delete(draft_series_id)

    def get_draft_series(self, draft_series_id: int):
        """Get a draft series by ID"""
        draft_series_data = self.get(draft_series_id)
        if not draft_series_data:
            raise NotFoundException(f"Draft series not found by ID: {draft_series_id}")
        return draft_series_data

    def get_draft_series_by_match(self, match_id: int):
        """Get all draft series for a match"""
        return self.getByMatchId(match_id)

    def delete_all_drafts_for_match(self, match_id: int):
        """Delete all draft series for a match"""
        self.deleteByMatchId(match_id)

    def convert_to_series(self, draft_series: DraftSeries):
        """Convert a draft series to a real series (DTO only, actual creation handled by SeriesService)"""
        # Create a Series from the draft data
        series_dto = Series(
            {
                "match_id": draft_series.match_id,
                "date_time": draft_series.date_time,
                "caster": draft_series.caster,
                "player1_id": draft_series.player1_id,
                "player2_id": draft_series.player2_id,
                "player1_score": draft_series.player1_score or 0,
                "player2_score": draft_series.player2_score or 0,
                "host_player_id": draft_series.host_player_id,
                "is_fantasy_match": draft_series.is_fantasy_match,
            }
        )
        return series_dto
