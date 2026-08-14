from app.database.team_season_db_service import TeamSeasonDBService
from app.schemas.season_info import SeasonInfo


class TeamSeasonAppService:
    def __init__(self, team_season_db_service: TeamSeasonDBService):
        self.team_season_db_service = team_season_db_service

    def update_team_season(self, team_id: int, season_info: SeasonInfo):
        season_info_data = self.team_season_db_service.update(team_id, season_info)
        return season_info_data
