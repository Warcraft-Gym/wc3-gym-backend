import logging
from src.database.abstract_database_service import AbstractDatabaseService
from src.database.model.DBUser import DBUser
from src.dtos.user_dto import UserDTO
from sqlalchemy.exc import SQLAlchemyError
from custom_exceptions import DBException
logger = logging.getLogger(__name__)

class UserDBService(AbstractDatabaseService):
    def add(self, name, email):
        try:
            session = self.Session()
            user = DBUser.add(session, name=name, email=email)
            # Example usage
            if not user:
                raise DBException("User could not be created!")
            return UserDTO.from_dbuser(user)              
        except SQLAlchemyError as e:
            # Log the error and handle it
            logger.error(f"Database error: {e}")
            raise DBException(f"Database error: {e}")
        finally:
            session.close()


    def update(self, user_id, name=None, email=None):
        try:
            session = self.Session()
            user = DBUser.update(session, user_id, name=name, email=email)
            # Example usage
            if not user:
                raise DBException("User could not be updated")
            return UserDTO.from_dbuser(user)
        except SQLAlchemyError as e:
            # Log the error and handle it
            logger.error(f"Database error: {e}")
            raise DBException(f"Database error: {e}")
        finally:
            session.close()

    def delete(self, user_id):
        try:
            session = self.Session()
            DBUser.delete(session, user_id)
        except SQLAlchemyError as e:
            # Log the error and handle it
            logger.error(f"Database error: {e}")
            raise DBException(f"Database error: {e}")
        finally:
            session.close()

    def get(self, user_id):
        try:
            session = self.Session()
            user = session.query(DBUser).filter_by(id=user_id).first()
            # Example usage
            if not user:
                return None
            return UserDTO.from_dbuser(user)
        except SQLAlchemyError as e:
            # Log the error and handle it
            logger.error(f"Database error: {e}")
            raise DBException(f"Database error: {e}")
        finally:
            session.close()
