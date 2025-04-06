from src.database.series_db_service import SeriesDBService
from src.dtos.series_dto import SeriesDTO
from src.service.score_service import ScoreAppService
from custom_exceptions import NotFoundException

class SeriesAppService:
    def __init__(self, series_service: SeriesDBService, score_app_service: ScoreAppService):
        self.series_service = series_service
        self.score_app_service = score_app_service
    
    def create_series(self, series: SeriesDTO):
        series.id = None
        series = self.score_app_service.calculateSeriesScore(series)
        series = self.series_service.add(series)

        series.match = self.score_app_service.updateMatchScore(series.match_id)

        return series
    
    def update_series(self, series_id: int, series: SeriesDTO):
        series.id = series_id
        series = self.score_app_service.calculateSeriesScore(series)
        series = self.series_service.update(series)

        series.match = self.score_app_service.updateMatchScore(series.match_id)

        return series
    
    def delete_series(self, series_id: int):
        self.series_service.delete(series_id)

    def get_series(self, series_id: int):
        series_data = self.series_service.get(series_id)
        if not series_data:
            raise NotFoundException(f"Series not found byId: {series_id}")
        return series_data
    
    def getAll(self):
        series_data = self.series_service.getAll()
        return series_data

    def search(self, query):
        series_data = self.series_service.search(query)
        return series_data
    
    def searchForSeason(self, season_id, query):
        series_data = self.series_service.searchForSeason(season_id, query)
        return series_data

    def searchForSeasonAndPlayday(self, season_id, playday, query):
        series_data = self.series_service.searchForSeasonAndPlayday(season_id, playday, query)
        return series_data