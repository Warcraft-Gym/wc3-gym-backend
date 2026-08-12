import logging
from src.database.abstract_database_service import AbstractDatabaseService

from src.database.model.DBUser import DBUser
from src.dtos.user_dto import UserDTO
from src.dtos.w3c_stats_dto import W3CStatsDTO
from src.database.model.DBW3CStats import DBW3CStats
from src.dtos.user_team_season_stats_dto import UserTeamSeasonStatsDTO
from sqlalchemy.orm import joinedload
from custom_exceptions import DBException
from src.util.query_util import QueryUtil

logger = logging.getLogger(__name__)

class UserDBService(AbstractDatabaseService):
    def add(self, user : UserDTO):
        with self.get_session() as session:
            user = DBUser.add(session, user.to_db_dict())
            if not user:
                raise DBException("User could not be created!")
            return UserDTO.from_dbuser(user)              


    def update(self, user: UserDTO):
        with self.get_session() as session:
            user = DBUser.update(session, user.id, **user.to_db_dict())
            if not user:
                raise DBException("User could not be updated")
            return UserDTO.from_dbuser(user)

    def delete(self, user_id):
        with self.get_session() as session:
            DBUser.delete(session, user_id)

    def get(self, user_id):
        with self.get_session() as session:
            # Eager load related entities, disable nested loading
            user = session.query(DBUser)\
                .options(
                    joinedload(DBUser.team_seasons).noload('*'),
                    joinedload(DBUser.w3c_stats)
                )\
                .filter_by(id=user_id).first()
            if not user:
                return None
            return UserDTO.from_dbuser(user)


    def search(self, query):
        with self.get_session() as session:
            result = []
            filter = QueryUtil.convertQueryToDBFilter(DBUser, query)
            # Eager load related entities, disable nested loading
            users = session.query(DBUser)\
                .options(
                    joinedload(DBUser.team_seasons).noload('*'),
                    joinedload(DBUser.w3c_stats)
                )\
                .filter(filter).all() if filter is not None else []
            if not users:
                logger.debug(f"No users found by searchcriteria: {query}")
                return result
                
            for user in users:
                result.append(UserDTO.from_dbuser(user))
            return result

    def getAll(self):
        with self.get_session() as session:
            from src.database.model.DBRelationships import DBUserTeamSeason
            result = []
            # Eager load related entities, disable nested loading
            users = session.query(DBUser)\
                .options(
                    joinedload(DBUser.team_seasons).joinedload(DBUserTeamSeason.season),
                    joinedload(DBUser.w3c_stats)
                ).all()
                
            for user in users:
                result.append(UserDTO.from_dbuser(user))
            return result

    def updateW3CStats(self, w3c_stats : W3CStatsDTO):
        with self.get_session() as session:
            stats = DBW3CStats.update(session, w3c_stats.id, **w3c_stats.to_dict())
            if not stats:
                raise DBException("W3CStats could not be updated")
            return W3CStatsDTO.from_dbw3cstats(stats)

    def createW3CStats(self, w3c_stats : W3CStatsDTO):
        with self.get_session() as session:
            stats = DBW3CStats.add(session, w3c_stats.to_db_dict())
            if not stats:
                raise DBException("W3CStats could not be created")
            return W3CStatsDTO.from_dbw3cstats(stats)
            

    def updateUserTeamSeasonStats(self, season_stats):
        with self.get_session() as session:
            stats = DBUser.updateUserTeamSeasonStats(session, season_stats)
            if not stats:
                raise DBException("User Team Season Stats could not be updated")
            return UserTeamSeasonStatsDTO.from_db_user_team_season(stats)
