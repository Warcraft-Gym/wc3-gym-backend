from app.database.draft_series_db_service import DraftSeriesDBService
from app.exceptions import NotFoundException
from app.schemas.draft_series import DraftSeries
from app.schemas.series import Series


class DraftSeriesAppService:
    def __init__(self, draft_series_service: DraftSeriesDBService):
        self.draft_series_service = draft_series_service

    def create_draft_series(self, draft_series: DraftSeries):
        """Create a new draft series"""
        draft_series.id = None
        return self.draft_series_service.add(draft_series)

    def update_draft_series(self, draft_series_id: int, draft_series: DraftSeries):
        """Update an existing draft series"""
        draft_series.id = draft_series_id
        return self.draft_series_service.update(draft_series)

    def delete_draft_series(self, draft_series_id: int):
        """Delete a draft series"""
        self.draft_series_service.delete(draft_series_id)

    def get_draft_series(self, draft_series_id: int):
        """Get a draft series by ID"""
        draft_series_data = self.draft_series_service.get(draft_series_id)
        if not draft_series_data:
            raise NotFoundException(f"Draft series not found by ID: {draft_series_id}")
        return draft_series_data

    def get_draft_series_by_match(self, match_id: int):
        """Get all draft series for a match"""
        return self.draft_series_service.getByMatchId(match_id)

    def delete_all_drafts_for_match(self, match_id: int):
        """Delete all draft series for a match"""
        self.draft_series_service.deleteByMatchId(match_id)

    def convert_to_series(self, draft_series: DraftSeries):
        """Convert a draft series to a real series (DTO only, actual creation handled by SeriesAppService)"""
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
