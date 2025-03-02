import logging
from src.database.abstract_database_service import AbstractDatabaseService
from src.database.model.DBSeason import DBSeason
from src.database.model.DBTeam import DBTeam
from sqlalchemy.exc import SQLAlchemyError
from custom_exceptions import DBException
from src.dtos.season_dto import SeasonDTO
from src.util.query_util import QueryUtil

logger = logging.getLogger(__name__)

class SeasonDBService(AbstractDatabaseService):
    def add(self, season : SeasonDTO):
        try:
            session = self.Session()
            new_season = DBSeason.add(session, season.to_dict())
            # Example usage
            if not new_season:
                raise DBException("Season could not be created!")
            return SeasonDTO.from_dbseason(new_season)   
        except SQLAlchemyError as e:
            # Log the error and handle it
            logger.error(f"Database error: {e}")
            raise DBException(f"Database error: {e}")
        finally:
            session.close()

    def update(self, season : SeasonDTO):
        try:
            session = self.Session()
            season = DBSeason.update(session, season.id, **season.to_dict())
            # Example usage
            if not season:
                raise DBException("Season could not be updated!")
            return SeasonDTO.from_dbseason(season)   
        except SQLAlchemyError as e:
            # Log the error and handle it
            logger.error(f"Database error: {e}")
            raise DBException(f"Database error: {e}")
        finally:
            session.close()

    def delete(self, season_id):
        try:
            session = self.Session()
            DBSeason.delete(session, season_id) 
        except SQLAlchemyError as e:
            # Log the error and handle it
            logger.error(f"Database error: {e}")
            raise DBException(f"Database error: {e}")
        finally:
            session.close()

    def get(self, season_id):
        try:
            session = self.Session()
            season = session.query(DBSeason).filter_by(id=season_id).first()
            # Example usage
            if not season:
                raise DBException("Season could not be found!")
            return SeasonDTO.from_dbseason(season)   
        except SQLAlchemyError as e:
            # Log the error and handle it
            logger.error(f"Database error: {e}")
            raise DBException(f"Database error: {e}")
        finally:
            session.close()

    def getAll(self):
        with self.get_session() as session:
            try:
                result = []
                seasons = DBSeason.getAll(session)
                for season in seasons:
                    result.append(SeasonDTO.from_dbseason(season))
                return result
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def addTeams(self, season_id, team_ids):
        with self.get_session() as session:
            try:
                season =  DBSeason.addTeams(session, season_id, team_ids)
                if not season:
                    raise DBException("Season could not be updated!")
                return SeasonDTO.from_dbseason(season)   
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def search(self, query):
        with self.get_session() as session:
            try:
                result = []
                filter = QueryUtil.convertQueryToDBFilter(DBSeason, query)
                seasons = DBSeason.seach(session, filter)
                if not seasons:
                    logger.debug(f"No seasons found by searchcriteria: {query}")
                    return result
                for season in seasons:
                    result.append(SeasonDTO.from_dbseason(season))
                return result
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def removeTeams(self, season_id, team_ids):
        with self.get_session() as session:
            try:
                season =  DBSeason.removeTeams(session, season_id, team_ids)
                if not season:
                    raise DBException("Season could not be updated!")
                return SeasonDTO.from_dbseason(season)   
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")