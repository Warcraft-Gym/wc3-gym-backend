from app.database.fantasy_team_db_service import FantasyTeamDBService
from app.exceptions import NotFoundException
from app.schemas.fantasy_team import FantasyTeam


class FantasyTeamAppService:
    def __init__(self, fantasy_team_service: FantasyTeamDBService):
        self.fantasy_team_service = fantasy_team_service

    def create_fantasy_team(self, team: FantasyTeam):
        team.id = None
        team_data = self.fantasy_team_service.add(team)
        return team_data

    def update_fantasy_team(self, team_id: int, team: FantasyTeam):
        team.id = team_id
        team_data = self.fantasy_team_service.update(team)
        return team_data

    def delete_fantasy_team(self, team_id: int):
        self.fantasy_team_service.delete(team_id)

    def get_fantasy_team(self, team_id: int):
        team_data = self.fantasy_team_service.get(team_id)
        if not team_data:
            raise NotFoundException(f"Fantasy Team not found by Id: {team_id}")
        return team_data

    def getAll_fantasy_teams(self):
        team_data = self.fantasy_team_service.getAll()
        return team_data

    def search_fantasy_teams(self, query):
        team_data = self.fantasy_team_service.search(query)
        return team_data

    def addFantasyPlayers(self, team_id: int, players):
        team_data = self.fantasy_team_service.addPlayers(team_id, players)
        return team_data

    def removeFantasyPlayers(self, team_id: int, players):
        team_data = self.fantasy_team_service.removePlayers(team_id, players)
        return team_data
