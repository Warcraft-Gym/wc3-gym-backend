from custom_exceptions import NotFoundException
from src.database.match_db_service import MatchDBService
from src.schemas.match import Match


class MatchAppService:
    def __init__(self, match_service: MatchDBService):
        self.match_service = match_service

    def create_match(self, match: Match):
        match_data = self.match_service.add(match)
        return match_data

    def update_match(self, match_id: int, match: Match):
        match_data = self.match_service.update(match_id, match)
        return match_data

    def delete_match(self, match_id: int):
        self.match_service.delete(match_id)

    def get_match(self, match_id: int):
        match_data = self.match_service.get(match_id)
        if not match_data:
            raise NotFoundException(f"Match not found by Id: {match_id}")
        return match_data

    def search(self, query):
        match_data = self.match_service.search(query)
        return match_data
