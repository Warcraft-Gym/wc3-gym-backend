from src.database.team_db_service import TeamDBService
from src.dtos.team_dto import TeamDTO
from custom_exceptions import NotFoundException

class TeamAppService:
    def __init__(self, team_service: TeamDBService):
        self.team_service = team_service

    def create_team(self, team: TeamDTO):
        team.id = None
        team_data = self.team_service.add(team)
        if(team_data):
            team_data = team_data.to_dict()
        return team_data

    def update_team(self, team_id: int, team: TeamDTO):
        team.id = team_id
        team_data = self.team_service.update(team)
        if(team_data):
            team_data = team_data.to_dict()
        return team_data

    def delete_team(self, team_id: int):
        self.team_service.delete(team_id)

    def get_team(self, team_id: int):
        team_data = self.team_service.get(team_id)
        if not team_data:
            raise NotFoundException(f"Team not found by Id: {team_id}")
        return team_data.to_dict()


    def addPlayers(self, team_id: int, players):
            team_data = self.team_service.addPlayers(team_id, players)
            if(team_data):
                team_data = team_data.to_dict()
            return team_data