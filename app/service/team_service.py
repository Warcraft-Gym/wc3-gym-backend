from app.database.team_db_service import TeamDBService
from app.exceptions import NotFoundException
from app.schemas.team import Team
from app.service.user_service import UserAppService


class TeamAppService:
    def __init__(self, team_service: TeamDBService, user_app_service: UserAppService):
        self.team_service = team_service
        self.user_app_service = user_app_service

    def create_team(self, team: Team):
        team.id = None
        team_data = self.team_service.add(team)
        return team_data

    def update_team(self, team_id: int, team: Team):
        team.id = team_id
        team_data = self.team_service.update(team)
        return team_data

    def update_team_icon(self, team_id: int, file):
        team_data = self.team_service.update_icon(team_id, file)
        return team_data

    def delete_team(self, team_id: int):
        self.team_service.delete(team_id)

    def get_team(self, team_id: int):
        team_data = self.team_service.get(team_id)
        if not team_data:
            raise NotFoundException(f"Team not found by Id: {team_id}")
        return team_data

    def get_team_icon(self, team_id: int):
        return self.team_service.get_icon(team_id)

    def get_team_season(self, team_id: int, season_id):
        team_data = self.team_service.get_with_nested_users_by_season(
            team_id, season_id
        )
        if not team_data:
            raise NotFoundException(f"Team not found by Id: {team_id}")
        # Data is already filtered by season at database level
        return team_data

    def addPlayers(self, team_id: int, season_id: int, players):
        team_data = self.team_service.addPlayers(team_id, season_id, players)
        return team_data

    def removePlayers(self, team_id: int, season_id: int, players):
        team_data = self.team_service.removePlayers(team_id, season_id, players)
        return team_data

    def setCoaches(self, team_id: int, season_id: int, coach_ids):
        """Set coaches for a team in a season (up to 3)"""
        team_data = self.team_service.setCoaches(team_id, season_id, coach_ids)
        return team_data

    def getAll(self):
        team_data = self.team_service.getAll()
        return team_data

    def getAll_basic(self):
        """Get all teams with basic info only (no users, no seasons)"""
        team_data = self.team_service.getAll_basic()
        return team_data

    def search(self, query):
        team_data = self.team_service.search(query)
        return team_data

    def get_teams_season(self, season_id: int):
        teams_data = self.team_service.getAll_with_nested_users()
        result = []
        if teams_data:
            for team_data in teams_data:
                # filter users and season info based on season id
                season_info = [
                    s_inf
                    for s_inf in team_data.seasons_info
                    if s_inf.season_id == season_id
                ]
                if not season_info:
                    # team not part of the requested season
                    continue
                team_data.seasons_info = season_info
                season_player = team_data.player_by_season.get(season_id)
                team_data.player_by_season = {season_id: season_player}
                team_data.seasons_info = [
                    seasons_info
                    for seasons_info in team_data.seasons_info
                    if seasons_info.season_id == season_id
                ]
                result.append(team_data)
        return result

    def get_teams_season_basic(self, season_id: int):
        """Get teams for a season with season_info but without users (for list views)"""
        teams_data = self.team_service.getAll_by_season(season_id)
        result = []
        if teams_data:
            for team_data in teams_data:
                # Filter season_info to only include the requested season
                team_data.seasons_info = [
                    s_inf
                    for s_inf in team_data.seasons_info
                    if s_inf.season_id == season_id
                ]
                result.append(team_data)
        return result

    def syncW3CStatsTeam(self, team_id, season_id):
        team = self.get_team_season(team_id, season_id)
        users = team.player_by_season.get(season_id)
        sync_errors = []

        if users:
            for u in users:
                try:
                    self.user_app_service.updateW3CStats(u)
                except Exception as e:
                    # Log the error but continue syncing other players
                    error_msg = f"Failed to sync W3C stats for user {u.name} (BattleTag: {u.battleTag}): {e!s}"
                    sync_errors.append(error_msg)
                    print(error_msg)  # Log to console

        # Return the updated team data even if some players failed
        result = self.get_team_season(team_id, season_id)

        # If there were errors, log them but don't fail the whole operation
        if sync_errors:
            print(
                f"W3C sync completed with {len(sync_errors)} error(s) for team {team_id}"
            )

        return result
