import logging

from app.exceptions import NotFoundException
from app.models.relationships import DBTeamSeason
from app.models.season_info import SeasonInfoPublic, SeasonInfoUpdate
from app.services.base import BaseService

logger = logging.getLogger(__name__)


class TeamSeasonService(BaseService):
    def add(self):
        return Exception("Method not available")

    def update(self, team_id: int, season_info: SeasonInfoUpdate):
        with self.get_session() as session:
            season_info = DBTeamSeason.updateSeasonInfo(
                session,
                season_info.season_id,
                team_id,
                **season_info.model_dump(),
            )
            if not season_info:
                raise NotFoundException("Team season not found")
            return SeasonInfoPublic.from_team_season(season_info)

    def delete(self):
        return Exception("Method not available")

    def get(self):
        return Exception("Method not available")

    def update_team_season(self, team_id: int, season_info: SeasonInfoUpdate):
        return self.update(team_id, season_info)
