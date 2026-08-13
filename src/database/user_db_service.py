import logging
from src.database.abstract_database_service import AbstractDatabaseService

from src.models.user import DBUser
from src.schemas.user import User
from src.schemas.w3c_stats import W3CStats
from src.models.w3c_stats import DBW3CStats
from src.schemas.user_team_season_stats import UserTeamSeasonStats
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from custom_exceptions import DBException
from src.util.query_util import QueryUtil

logger = logging.getLogger(__name__)

class UserDBService(AbstractDatabaseService):
    def add(self, user : User):
        with self.get_session() as session:
            user = DBUser.add(session, user.to_db_dict())
            if not user:
                raise DBException("User could not be created!")
            return User.from_dbuser(user)              


    def update(self, user: User):
        with self.get_session() as session:
            user = DBUser.update(session, user.id, **user.to_db_dict())
            if not user:
                raise DBException("User could not be updated")
            return User.from_dbuser(user)

    def delete(self, user_id):
        with self.get_session() as session:
            DBUser.delete(session, user_id)

    def get(self, user_id):
        with self.get_session() as session:
            # Eager load related entities, disable nested loading
            user = session.scalars(
                select(DBUser)
                .options(
                    joinedload(DBUser.team_seasons).noload('*'),
                    joinedload(DBUser.w3c_stats)
                )
                .where(DBUser.id == user_id)
            ).unique().first()
            if not user:
                return None
            return User.from_dbuser(user)


    def search(self, query):
        with self.get_session() as session:
            result = []
            filter = QueryUtil.convertQueryToDBFilter(DBUser, query)
            # Eager load related entities, disable nested loading
            users = session.scalars(
                select(DBUser)
                .options(
                    joinedload(DBUser.team_seasons).noload('*'),
                    joinedload(DBUser.w3c_stats)
                )
                .where(filter)
            ).unique().all() if filter is not None else []
            if not users:
                logger.debug(f"No users found by searchcriteria: {query}")
                return result
                
            for user in users:
                result.append(User.from_dbuser(user))
            return result

    def getAll(self):
        with self.get_session() as session:
            from src.models.relationships import DBUserTeamSeason
            result = []
            # Eager load related entities, disable nested loading
            users = session.scalars(
                select(DBUser)
                .options(
                    joinedload(DBUser.team_seasons).joinedload(DBUserTeamSeason.season),
                    joinedload(DBUser.w3c_stats)
                )
            ).unique().all()
                
            for user in users:
                result.append(User.from_dbuser(user))
            return result

    def updateW3CStats(self, w3c_stats : W3CStats):
        with self.get_session() as session:
            stats = DBW3CStats.update(session, w3c_stats.id, **w3c_stats.to_db_dict())
            if not stats:
                raise DBException("W3CStats could not be updated")
            return W3CStats.from_dbw3cstats(stats)

    def createW3CStats(self, w3c_stats : W3CStats):
        with self.get_session() as session:
            stats = DBW3CStats.add(session, w3c_stats.to_db_dict())
            if not stats:
                raise DBException("W3CStats could not be created")
            return W3CStats.from_dbw3cstats(stats)
            

    def updateUserTeamSeasonStats(self, season_stats):
        with self.get_session() as session:
            stats = DBUser.updateUserTeamSeasonStats(session, season_stats)
            if not stats:
                raise DBException("User Team Season Stats could not be updated")
            return UserTeamSeasonStats.from_db_user_team_season(stats)
