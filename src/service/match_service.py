from src.database.match_db_service import MatchDBService
from src.dtos.match_dto import MatchDTO
from custom_exceptions import NotFoundException

class MatchAppService:
    def __init__(self, match_service: MatchDBService):
        self.match_service = match_service

    def create_match(self, team1_id: int, team2_id: int, score: str):
        match_data = self.match_service.add(team1_id=team1_id, team2_id=team2_id, score=score)
        if(match_data):
            match_data = match_data.to_dict()
        return match_data

    def update_match(self, match_id: int, score: str = None):
        match_data = self.match_service.update(match_id, score=score)
        if(match_data):
            match_data = match_data.to_dict()
        return match_data

    def delete_match(self, match_id: int):
        self.match_service.delete(match_id)

    def get_match(self, match_id: int):
        match_data = self.match_service.get(match_id)
        if not match_data:
            raise NotFoundException(f"Match not found by Id: {match_id}")
        return match_data.to_dict()
