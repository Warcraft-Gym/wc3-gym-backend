from src.database.season_db_service import SeasonDBService
from src.schemas.season import Season
from custom_exceptions import NotFoundException

class SeasonAppService:
    def __init__(self, season_service: SeasonDBService):
        self.season_service = season_service

    def create_season(self, season: Season):
        season.id = None
        season_data = self.season_service.add(season)
        return season_data

    def update_season(self, season_id: int, season: Season):
        season.id = season_id
        season_data = self.season_service.update(season)
        return season_data

    def delete_season(self, season_id: int):
        self.season_service.delete(season_id)

    def get_season(self, season_id: int):
        season_data = self.season_service.get(season_id)
        if not season_data:
            raise NotFoundException(f"Season not found by Id: {season_id}")
        return season_data
    
    def getAll(self):
        season_data = self.season_service.getAll()
        return season_data
    
    def addTeams(self, season_id: int, team_ids):
        season_data = self.season_service.addTeams(season_id, team_ids)
        return season_data
      
    def removeTeams(self, season_id: int, team_ids):
        season_data = self.season_service.removeTeams(season_id, team_ids)
        return season_data
    
    def search(self, query):
        season_data = self.season_service.search(query)
        return season_data
    
    def addMaps(self, season_id: int, map_ids):
        season_data = self.season_service.addMaps(season_id, map_ids)
        return season_data
      
    def removeMaps(self, season_id: int, map_ids):
        season_data = self.season_service.removeMaps(season_id, map_ids)
        return season_data

    def addUserSignup(self, season_id: int, user_ids):
        season_data = self.season_service.addUserSignup(season_id, user_ids)
        return season_data
      
    def removeUserSignup(self, season_id: int, user_ids):
        season_data = self.season_service.removeUserSignup(season_id, user_ids)
        return season_data
    
    def getSignedUpUsers(self, season_id: int):
        users = self.season_service.getSignedUpUsers(season_id)
        return users