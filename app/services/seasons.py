import logging

from sqlalchemy import select
from sqlalchemy.orm import joinedload, noload

from app.exceptions import NotFoundException
from app.models.season import Season, SeasonCreate, SeasonPublic, SeasonUpdate
from app.models.user import UserPublic
from app.services.base import BaseService
from app.utils.query_util import QueryElement, QueryUtil

logger = logging.getLogger(__name__)


class SeasonService(BaseService):
    def add(self, season: SeasonCreate) -> SeasonPublic:
        with self.get_session() as session:
            new_season = Season.add(session, season.model_dump())
            return SeasonPublic.from_season(new_season)

    def update(self, season_id: int, season: SeasonUpdate) -> SeasonPublic:
        with self.get_session() as session:
            season = Season.update(
                session, season_id, **season.model_dump(exclude_unset=True)
            )
            # Example usage
            if not season:
                raise NotFoundException("Season not found")
            return SeasonPublic.from_season(season)

    def delete(self, season_id: int) -> None:
        with self.get_session() as session:
            Season.delete(session, season_id)

    def get(self, season_id: int) -> SeasonPublic:
        with self.get_session() as session:
            from app.models.relationships import DBMapSeason

            # Eager load related entities, disable nested loading except for maps
            season = (
                session.scalars(
                    select(Season)
                    .options(
                        joinedload(Season.user_teams).noload("*"),
                        joinedload(Season.teams).noload("*"),
                        joinedload(Season.maps).joinedload(DBMapSeason.map),
                        noload(Season.signup_users),
                    )
                    .where(Season.id == season_id)
                )
                .unique()
                .first()
            )
            # Example usage
            if not season:
                raise NotFoundException("Season not found")
            return SeasonPublic.from_season(season)

    def getAll(self) -> list[SeasonPublic]:
        with self.get_session() as session:
            result = []
            from app.models.relationships import DBMapSeason

            # Eager load related entities, disable nested loading except for maps
            seasons = (
                session.scalars(
                    select(Season).options(
                        joinedload(Season.user_teams).noload("*"),
                        joinedload(Season.teams).noload("*"),
                        joinedload(Season.maps).joinedload(DBMapSeason.map),
                        noload(Season.signup_users),
                    )
                )
                .unique()
                .all()
            )
            for season in seasons:
                result.append(SeasonPublic.from_season(season))
            return result

    def addTeams(self, season_id: int, team_ids: list[int]) -> SeasonPublic:
        with self.get_session() as session:
            season = Season.addTeams(session, season_id, team_ids)
            return SeasonPublic.from_season(season)

    def search(self, query: QueryElement | None) -> list[SeasonPublic]:
        with self.get_session() as session:
            result = []
            from app.models.relationships import DBMapSeason

            filter = QueryUtil.convertQueryToDBFilter(Season, query)
            # Eager load related entities, disable nested loading except for maps
            seasons = (
                session.scalars(
                    select(Season)
                    .options(
                        joinedload(Season.user_teams).noload("*"),
                        joinedload(Season.teams).noload("*"),
                        joinedload(Season.maps).joinedload(DBMapSeason.map),
                        noload(Season.signup_users),
                    )
                    .where(filter)
                )
                .unique()
                .all()
                if filter is not None
                else []
            )
            if not seasons:
                logger.debug(f"No seasons found by searchcriteria: {query}")
                return result
            for season in seasons:
                result.append(SeasonPublic.from_season(season))
            return result

    def removeTeams(self, season_id: int, team_ids: list[int]) -> SeasonPublic:
        with self.get_session() as session:
            season = Season.removeTeams(session, season_id, team_ids)
            return SeasonPublic.from_season(season)

    def addMaps(self, season_id: int, map_ids: list[int]) -> SeasonPublic:
        with self.get_session() as session:
            season = Season.addMaps(session, season_id, map_ids)
            return SeasonPublic.from_season(season)

    def removeMaps(self, season_id: int, map_ids: list[int]) -> SeasonPublic:
        with self.get_session() as session:
            season = Season.removeMaps(session, season_id, map_ids)
            return SeasonPublic.from_season(season)

    def addUserSignup(self, season_id: int, user_ids: list[int]) -> SeasonPublic:
        with self.get_session() as session:
            season = Season.addUserSignup(session, season_id, user_ids)
            return SeasonPublic.from_season(season)

    def removeUserSignup(self, season_id: int, user_ids: list[int]) -> SeasonPublic:
        with self.get_session() as session:
            season = Season.removeUserSignup(session, season_id, user_ids)
            return SeasonPublic.from_season(season)

    def getSignedUpUsers(self, season_id: int) -> list[UserPublic]:
        with self.get_session() as session:
            from app.models.relationships import DBUserSeasonSignup
            from app.models.user import User

            # Eager load signup users with their user data and w3c_stats
            season = (
                session.scalars(
                    select(Season)
                    .options(
                        joinedload(Season.signup_users)
                        .joinedload(DBUserSeasonSignup.user)
                        .joinedload(User.w3c_stats)
                        .noload("*"),
                        joinedload(Season.signup_users)
                        .joinedload(DBUserSeasonSignup.user)
                        .joinedload(User.team_seasons)
                        .noload("*"),
                    )
                    .where(Season.id == season_id)
                )
                .unique()
                .first()
            )

            if not season:
                raise NotFoundException("Season not found")

            result = []
            if season.signup_users:
                for signup in season.signup_users:
                    if signup.user:
                        user_dto = UserPublic.from_user(signup.user)
                        if user_dto:
                            result.append(user_dto)

            return result

    def create_season(self, season: SeasonCreate) -> SeasonPublic:
        return self.add(season)

    def update_season(self, season_id: int, season: SeasonUpdate) -> SeasonPublic:
        return self.update(season_id, season)

    def delete_season(self, season_id: int) -> None:
        self.delete(season_id)

    def get_season(self, season_id: int) -> SeasonPublic:
        season_data = self.get(season_id)
        if not season_data:
            raise NotFoundException(f"Season not found by Id: {season_id}")
        return season_data
