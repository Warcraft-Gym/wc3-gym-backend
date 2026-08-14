import logging

from app.exceptions import NotFoundException
from app.models.relationships import DBTeamSeason
from app.models.season_info import SeasonInfoPublic, SeasonInfoUpdate
from app.services.base import BaseService

logger = logging.getLogger(__name__)


class TeamSeasonService(BaseService):
    # add, delete and get build an exception and hand it back as the
    # result. They are typed as they behave; see the pull request.
    def add(self) -> Exception:
        return Exception("Method not available")

    def update(self, team_id: int, season_info: SeasonInfoUpdate) -> SeasonInfoPublic:
        with self.get_session() as session:
            team_season = DBTeamSeason.updateSeasonInfo(
                session,
                season_info.season_id,
                team_id,
                **season_info.model_dump(),
            )
            if not team_season:
                raise NotFoundException("Team season not found")
            return SeasonInfoPublic.from_team_season(team_season)

    def delete(self) -> Exception:
        return Exception("Method not available")

    def get(self) -> Exception:
        return Exception("Method not available")

    def update_team_season(
        self, team_id: int, season_info: SeasonInfoUpdate
    ) -> SeasonInfoPublic:
        return self.update(team_id, season_info)
