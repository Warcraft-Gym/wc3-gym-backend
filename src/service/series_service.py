from src.database.series_db_service import SeriesDBService
from src.dtos.series_dto import SeriesDTO
from custom_exceptions import NotFoundException

class SeriesAppService:
    def __init__(self, series_service: SeriesDBService):
        self.series_service = series_service
    
    def create_series(self, match_id: int, player1_id: int, player2_id: int, score:str):
        series_data = self.series_service.add(match_id=match_id, player1_id=player1_id, player2_id=player2_id, score=score)
        if(series_data):
            series_data = series_data.to_dict()
        return series_data
    
    def update_series(self, series_id: int, player1_id: None, player2_id: None, score: None):
        series_data = self.series_service.update(series_id, player1_id=player1_id, player2_id=player2_id, score=score)
        if(series_data):
            series_data = series_data.to_dict()
        return series_data
    
    def delete_series(self, series_id: int):
        self.series_serivce.delete(series_id)

    def get_series(self, series_id: int):
        series_data = self.series_service.get(series_id)
        if not series_data:
            raise NotFoundException(f"Series not found byId: {series_id}")
        return series_data.to_dict()
    
    def getAll(self):
        series_data = self.series_service.getAll()
        series_dict_l = []
        for sd in series_data:
            series_dict_l.append(sd.to_dict())
        return series_dict_l
