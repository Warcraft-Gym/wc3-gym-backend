from src.database.team_db_service import TeamDBService
from src.dtos.team_dto import TeamDTO

class TeamAppService:
    def __init__(self, team_service: TeamDBService):
        self.team_service = team_service

    def create_team(self, name: str):
        team_data = self.team_service.add(name=name)
        team_dto = TeamDTO.from_dict(team_data.__dict__)
        return team_dto.to_dict()

    def update_team(self, team_id: int, name: str = None):
        team_data = self.team_service.update(team_id, name=name)
        team_dto = TeamDTO.from_dict(team_data.__dict__)
        return team_dto.to_dict()

    def delete_team(self, team_id: int):
        self.team_service.delete(team_id)

    def get_team(self, team_id: int):
        team_data = self.team_service.get(team_id)
        team_dto = TeamDTO.from_dict(team_data.__dict__)
        return team_dto.to_dict()
