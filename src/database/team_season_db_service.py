import logging
from src.database.abstract_database_service import AbstractDatabaseService
from src.database.model.DBRelationships import DBTeamSeason
from sqlalchemy.exc import SQLAlchemyError
from custom_exceptions import DBException
from src.dtos.season_info_dto import SeasonInfoDTO

logger = logging.getLogger(__name__)

class TeamSeasonDBService(AbstractDatabaseService):
    def add(self):
        return Exception("Method not available")
    
    def update(self, team_id: int, season_info : SeasonInfoDTO):
        with self.get_session() as session:
            try:
                season_info = DBTeamSeason.updateSeasonInfo(session, season_info.season_id, team_id, **season_info.to_db_dict())
                if not season_info:
                    raise DBException("Season could not be updated!")
                return SeasonInfoDTO.from_dbseasoninfo(season_info)

            except SQLAlchemyError as e:
                # Log the error and handle it
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")
    
    def delete(self):
        return Exception("Method not available")
    
    def get(self):
        return Exception("Method not available")