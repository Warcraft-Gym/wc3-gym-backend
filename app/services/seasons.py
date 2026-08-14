import logging

from sqlalchemy import select
from sqlalchemy.orm import joinedload, noload

from app.exceptions import NotFoundException
from app.models.season import DBSeason
from app.schemas.season import Season
from app.services.base import BaseService
from app.utils.query_util import QueryUtil

logger = logging.getLogger(__name__)


class SeasonService(BaseService):
    def add(self, season: Season):
        with self.get_session() as session:
            new_season = DBSeason.add(session, season.to_db_dict())
            return Season.from_dbseason(new_season)

    def update(self, season: Season):
        with self.get_session() as session:
            season = DBSeason.update(session, season.id, **season.to_db_dict())
            # Example usage
            if not season:
                raise NotFoundException("Season not found")
            return Season.from_dbseason(season)

    def delete(self, season_id):
        with self.get_session() as session:
            DBSeason.delete(session, season_id)

    def get(self, season_id):
        with self.get_session() as session:
            from app.models.relationships import DBMapSeason

            # Eager load related entities, disable nested loading except for maps
            season = (
                session.scalars(
                    select(DBSeason)
                    .options(
                        joinedload(DBSeason.user_teams).noload("*"),
                        joinedload(DBSeason.teams).noload("*"),
                        joinedload(DBSeason.maps).joinedload(DBMapSeason.map),
                        noload(DBSeason.signup_users),
                    )
                    .where(DBSeason.id == season_id)
                )
                .unique()
                .first()
            )
            # Example usage
            if not season:
                raise NotFoundException("Season not found")
            return Season.from_dbseason(season)

    def getAll(self):
        with self.get_session() as session:
            result = []
            from app.models.relationships import DBMapSeason

            # Eager load related entities, disable nested loading except for maps
            seasons = (
                session.scalars(
                    select(DBSeason).options(
                        joinedload(DBSeason.user_teams).noload("*"),
                        joinedload(DBSeason.teams).noload("*"),
                        joinedload(DBSeason.maps).joinedload(DBMapSeason.map),
                        noload(DBSeason.signup_users),
                    )
                )
                .unique()
                .all()
            )
            for season in seasons:
                result.append(Season.from_dbseason(season))
            return result

    def addTeams(self, season_id, team_ids):
        with self.get_session() as session:
            season = DBSeason.addTeams(session, season_id, team_ids)
            return Season.from_dbseason(season)

    def search(self, query):
        with self.get_session() as session:
            result = []
            from app.models.relationships import DBMapSeason

            filter = QueryUtil.convertQueryToDBFilter(DBSeason, query)
            # Eager load related entities, disable nested loading except for maps
            seasons = (
                session.scalars(
                    select(DBSeason)
                    .options(
                        joinedload(DBSeason.user_teams).noload("*"),
                        joinedload(DBSeason.teams).noload("*"),
                        joinedload(DBSeason.maps).joinedload(DBMapSeason.map),
                        noload(DBSeason.signup_users),
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
                result.append(Season.from_dbseason(season))
            return result

    def removeTeams(self, season_id, team_ids):
        with self.get_session() as session:
            season = DBSeason.removeTeams(session, season_id, team_ids)
            return Season.from_dbseason(season)

    def addMaps(self, season_id, map_ids):
        with self.get_session() as session:
            season = DBSeason.addMaps(session, season_id, map_ids)
            return Season.from_dbseason(season)

    def removeMaps(self, season_id, map_ids):
        with self.get_session() as session:
            season = DBSeason.removeMaps(session, season_id, map_ids)
            return Season.from_dbseason(season)

    def addUserSignup(self, season_id, user_ids):
        with self.get_session() as session:
            season = DBSeason.addUserSignup(session, season_id, user_ids)
            return Season.from_dbseason(season)

    def removeUserSignup(self, season_id, user_ids):
        with self.get_session() as session:
            season = DBSeason.removeUserSignup(session, season_id, user_ids)
            return Season.from_dbseason(season)

    def getSignedUpUsers(self, season_id):
        with self.get_session() as session:
            from app.models.relationships import DBUserSeasonSignup
            from app.models.user import DBUser
            from app.schemas.user import User

            # Eager load signup users with their user data and w3c_stats
            season = (
                session.scalars(
                    select(DBSeason)
                    .options(
                        joinedload(DBSeason.signup_users)
                        .joinedload(DBUserSeasonSignup.user)
                        .joinedload(DBUser.w3c_stats)
                        .noload("*"),
                        joinedload(DBSeason.signup_users)
                        .joinedload(DBUserSeasonSignup.user)
                        .joinedload(DBUser.team_seasons)
                        .noload("*"),
                    )
                    .where(DBSeason.id == season_id)
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
                        user_dto = User.from_dbuser(signup.user)
                        if user_dto:
                            result.append(user_dto)

            return result

    def create_season(self, season: Season):
        season.id = None
        return self.add(season)

    def update_season(self, season_id: int, season: Season):
        season.id = season_id
        return self.update(season)

    def delete_season(self, season_id: int):
        self.delete(season_id)

    def get_season(self, season_id: int):
        season_data = self.get(season_id)
        if not season_data:
            raise NotFoundException(f"Season not found by Id: {season_id}")
        return season_data
