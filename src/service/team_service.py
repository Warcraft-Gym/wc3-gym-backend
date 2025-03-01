from src.database.team_db_service import TeamDBService
from src.dtos.team_dto import TeamDTO
from custom_exceptions import NotFoundException

class TeamAppService:
    def __init__(self, team_service: TeamDBService):
        self.team_service = team_service

    def create_team(self, team: TeamDTO):
        team.id = None
        team_data = self.team_service.add(team)
        return team_data

    def update_team(self, team_id: int, team: TeamDTO):
        team.id = team_id
        team_data = self.team_service.update(team)
        return team_data

    def delete_team(self, team_id: int):
        self.team_service.delete(team_id)

    def get_team(self, team_id: int):
        team_data = self.team_service.get(team_id)
        if not team_data:
            raise NotFoundException(f"Team not found by Id: {team_id}")
        return team_data
    
    def get_team_season(self, team_id: int, season_id):
        team_data = self.team_service.get(team_id)
        if not team_data:
            raise NotFoundException(f"Team not found by Id: {team_id}")
        # filter users and season info based on season id
        season_player = team_data.player_by_season.get(season_id)
        team_data.player_by_season = {season_id : season_player}
        team_data.seasons_info = [seasons_info for seasons_info in team_data.seasons_info if seasons_info.season_id == season_id]

        return team_data

    def addPlayers(self, team_id: int, season_id: int, players):
            team_data = self.team_service.addPlayers(team_id, season_id, players)
            return team_data
      
    def removePlayers(self, team_id: int, season_id: int, players):
            team_data = self.team_service.removePlayers(team_id, season_id, players)
            return team_data
    
    def getAll(self):
        team_data = self.team_service.getAll()
        return team_data

    def search(self, query):
        team_data = self.team_service.search(query)
        return team_data