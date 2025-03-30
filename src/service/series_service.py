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
        series_data = self.series_service.add(series)
        return series_data
    
    def update_series(self, series_id: int, series: SeriesDTO):
        series.id = series_id
        series_data = self.series_service.update(series)
        return series_data
    
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