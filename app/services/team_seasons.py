import logging

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.exceptions import NotFoundError
from app.models.season_info import SeasonInfoPublic, SeasonInfoUpdate
from app.models.team_season import DBTeamSeason
from app.services.base import BaseService

logger = logging.getLogger(__name__)


class TeamSeasonService(BaseService):
    # add, delete and get return an exception instead of raising it
    def add(self) -> Exception:
        return Exception("Method not available")

    def update(self, team_id: int, season_info: SeasonInfoUpdate) -> SeasonInfoPublic:
        with self.get_session() as session:
            # Eager load related entities to prevent N+1 queries
            team_season = session.scalars(
                select(DBTeamSeason)
                .options(joinedload(DBTeamSeason.team), joinedload(DBTeamSeason.season))
                .where(
                    DBTeamSeason.team_id == team_id,
                    DBTeamSeason.season_id == season_info.season_id,
                )
                .limit(1)
            ).first()
            if not team_season:
                raise NotFoundError("Team season not found")
            for key, value in season_info.model_dump().items():
                setattr(team_season, key, value)
            session.flush()
            return SeasonInfoPublic.from_team_season(team_season)

    def delete(self) -> Exception:
        return Exception("Method not available")

    def get(self) -> Exception:
        return Exception("Method not available")

    def update_team_season(
        self, team_id: int, season_info: SeasonInfoUpdate
    ) -> SeasonInfoPublic:
        return self.update(team_id, season_info)
