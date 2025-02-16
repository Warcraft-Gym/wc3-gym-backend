import logging
from src.database.abstract_database_service import AbstractDatabaseService
from src.database.model.DBUser import DBUser
from src.dtos.user_dto import UserDTO
from sqlalchemy.exc import SQLAlchemyError
from custom_exceptions import DBException
from src.util.query_util import QueryUtil

logger = logging.getLogger(__name__)

class UserDBService(AbstractDatabaseService):
    def add(self, user : UserDTO):
        with self.get_session() as session:
            try:
                user = DBUser.add(session, user.to_dict())
                if not user:
                    raise DBException("User could not be created!")
                return UserDTO.from_dbuser(user)              
            except SQLAlchemyError as e:
                # Log the error and handle it
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")


    def update(self, user):
        with self.get_session() as session:
            try:
                user = DBUser.update(session, user.id, **user.to_dict())
                if not user:
                    raise DBException("User could not be updated")
                return UserDTO.from_dbuser(user)
            except SQLAlchemyError as e:
                # Log the error and handle it
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def delete(self, user_id):
        with self.get_session() as session:
            try:
                DBUser.delete(session, user_id)
            except SQLAlchemyError as e:
                # Log the error and handle it
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def get(self, user_id):
        with self.get_session() as session:
            try:
                user = DBUser.getById(session, user_id)
                if not user:
                    return None
                return UserDTO.from_dbuser(user)
            except SQLAlchemyError as e:
                # Log the error and handle it
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")


    def search(self, query):
        with self.get_session() as session:
            try:
                result = []
                filter = QueryUtil.convertQueryToDBFilter(DBUser, query)
                users = DBUser.seach(session, filter)
                if not users:
                    logger.debug(f"No users found by searchcriteria: {query}")
                    return result
                
                for user in users:
                    result.append(UserDTO.from_dbuser(user))
                return result
            except SQLAlchemyError as e:
                # Log the error and handle it
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def getAll(self):
        with self.get_session() as session:
            try:
                result = []
                users = DBUser.getAll(session)
                
                for user in users:
                    result.append(UserDTO.from_dbuser(user))
                return result
            except SQLAlchemyError as e:
                # Log the error and handle it
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")