import logging

from sqlalchemy import delete, select
from sqlalchemy.orm import joinedload

from app.exceptions import NotFoundException
from app.models.draft_series import (
    DraftSeries,
    DraftSeriesCreate,
    DraftSeriesPublic,
    DraftSeriesUpdate,
)
from app.models.match import Match
from app.models.relationships import DBUserTeamSeason
from app.models.series import SeriesCreate
from app.models.user import User
from app.services.base import BaseService

logger = logging.getLogger(__name__)


class DraftSeriesService(BaseService):
    def add(self, draft_series: DraftSeriesCreate):
        with self.get_session() as session:
            draft_series = DraftSeries.add(session, draft_series.model_dump())
            return DraftSeriesPublic.from_draft_series(draft_series)

    def update(self, draft_series_id, draft_series: DraftSeriesUpdate):
        with self.get_session() as session:
            draft_series = DraftSeries.update(
                session,
                draft_series_id,
                **draft_series.model_dump(exclude_unset=True),
            )
            if not draft_series:
                raise NotFoundException("Draft series not found")
            return DraftSeriesPublic.from_draft_series(draft_series)

    def delete(self, draft_series_id):
        with self.get_session() as session:
            DraftSeries.delete(session, draft_series_id)

    def get(self, draft_series_id):
        with self.get_session() as session:
            # Eager load relationships to avoid N+1 queries
            draft_series = (
                session.scalars(
                    select(DraftSeries)
                    .options(
                        joinedload(DraftSeries.match).joinedload(Match.team1),
                        joinedload(DraftSeries.match).joinedload(Match.team2),
                        joinedload(DraftSeries.player1).joinedload(User.w3c_stats),
                        joinedload(DraftSeries.player1)
                        .joinedload(User.team_seasons)
                        .joinedload(DBUserTeamSeason.season),
                        joinedload(DraftSeries.player2).joinedload(User.w3c_stats),
                        joinedload(DraftSeries.player2)
                        .joinedload(User.team_seasons)
                        .joinedload(DBUserTeamSeason.season),
                    )
                    .where(DraftSeries.id == draft_series_id)
                )
                .unique()
                .first()
            )
            if not draft_series:
                raise NotFoundException("Draft series not found")
            return DraftSeriesPublic.from_draft_series(draft_series)

    def getByMatchId(self, match_id):
        with self.get_session() as session:
            result = []
            # Eager load relationships
            draft_series_list = (
                session.scalars(
                    select(DraftSeries)
                    .options(
                        joinedload(DraftSeries.match).joinedload(Match.team1),
                        joinedload(DraftSeries.match).joinedload(Match.team2),
                        joinedload(DraftSeries.player1).joinedload(User.w3c_stats),
                        joinedload(DraftSeries.player1)
                        .joinedload(User.team_seasons)
                        .joinedload(DBUserTeamSeason.season),
                        joinedload(DraftSeries.player2).joinedload(User.w3c_stats),
                        joinedload(DraftSeries.player2)
                        .joinedload(User.team_seasons)
                        .joinedload(DBUserTeamSeason.season),
                    )
                    .where(DraftSeries.match_id == match_id)
                )
                .unique()
                .all()
            )
            for single_draft_series in draft_series_list:
                result.append(DraftSeriesPublic.from_draft_series(single_draft_series))
            return result

    def deleteByMatchId(self, match_id):
        """Delete all draft series for a given match"""
        with self.get_session() as session:
            session.execute(delete(DraftSeries).where(DraftSeries.match_id == match_id))

    def create_draft_series(self, draft_series: DraftSeriesCreate):
        """Create a new draft series"""
        return self.add(draft_series)

    def update_draft_series(
        self, draft_series_id: int, draft_series: DraftSeriesUpdate
    ):
        """Update an existing draft series"""
        return self.update(draft_series_id, draft_series)

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
        series_dto = SeriesCreate(
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
        return series_dto
