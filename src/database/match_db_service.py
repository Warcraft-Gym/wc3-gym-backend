import logging
from src.database.abstract_database_service import AbstractDatabaseService
from src.database.model.DBMatch import DBMatch
from sqlalchemy.exc import SQLAlchemyError
from custom_exceptions import DBException
from src.util.query_util import QueryUtil
from src.dtos.match_dto import MatchDTO

logger = logging.getLogger(__name__)

class MatchDBService(AbstractDatabaseService):
    def add(self, match: MatchDTO):
        try:
            session = self.Session()
            match = DBMatch.add(session, match.to_db_dict())
            # Example usage
            if not match:
                logger.error("Match could not be created!")
                raise DBException("Match could not be created!")
            return MatchDTO.from_dbmatch(match)   
        except SQLAlchemyError as e:
            # Log the error and handle it
            logger.error(f"Database error: {e}")
            raise DBException(f"Database error: {e}")
        finally:
            session.close()

    def update(self, match_id, match: MatchDTO):
        try:
            session = self.Session()
            match = DBMatch.update(session, match_id, **match.to_db_dict())
            # Example usage
            if not match:
                logger.error("Match could not be updated!")
                raise DBException("Match could not be updated!")
            return MatchDTO.from_dbmatch(match)   
        except SQLAlchemyError as e:
            # Log the error and handle it
            logger.error(f"Database error: {e}")
            raise DBException(f"Database error: {e}")
        finally:
            session.close()

    def delete(self, match_id):
        try:
            session = self.Session()
            DBMatch.delete(session, match_id)
        except SQLAlchemyError as e:
            # Log the error and handle it
            logger.error(f"Database error: {e}")
            raise DBException(f"Database error: {e}")
        finally:
            session.close()

    def get(self, match_id):
        try:
            session = self.Session()
            match = session.query(DBMatch).filter_by(id=match_id).first()
            # Example usage
            if not match:
                logger.error("Match could not be found!")
                raise DBException("Match could not be found!")
            return MatchDTO.from_dbmatch(match)   
        except SQLAlchemyError as e:
            # Log the error and handle it
            logger.error(f"Database error: {e}")
            raise DBException(f"Database error: {e}")
        finally:
            session.close()

    def search(self, query):
        with self.get_session() as session:
            try:
                result = []
                filter = QueryUtil.convertQueryToDBFilter(DBMatch, query)
                matches = DBMatch.search(session, filter)
                if not matches:
                    logger.debug(f"No matches found by searchcriteria: {query}")
                    return result
                for match in matches:
                    result.append(MatchDTO.from_dbmatch(match))
                return result
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")