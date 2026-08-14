import logging

from app.exceptions import DBException
from app.models.relationships import DBTeamSeason
from app.schemas.season_info import SeasonInfo
from app.services.base import BaseService

logger = logging.getLogger(__name__)


class TeamSeasonService(BaseService):
    def add(self):
        return Exception("Method not available")

    def update(self, team_id: int, season_info: SeasonInfo):
        with self.get_session() as session:
            season_info = DBTeamSeason.updateSeasonInfo(
                session, season_info.season_id, team_id, **season_info.to_db_dict()
            )
            if not season_info:
                raise DBException("Season could not be updated!")
            return SeasonInfo.from_dbseasoninfo(season_info)

    def delete(self):
        return Exception("Method not available")

    def get(self):
        return Exception("Method not available")

    def update_team_season(self, team_id: int, season_info: SeasonInfo):
        return self.update(team_id, season_info)
