import logging
from src.database.abstract_database_service import AbstractDatabaseService
from src.database.model.DBTeam import DBTeam
from sqlalchemy.exc import SQLAlchemyError
from custom_exceptions import DBException
from src.dtos.team_dto import TeamDTO
from typing import List

logger = logging.getLogger(__name__)

class TeamDBService(AbstractDatabaseService):
    def add(self, team : TeamDTO):
        try:
            session = self.Session()
            new_team = DBTeam.add(session, team.to_dict())
            # Example usage
            if not new_team:
                raise DBException("Team could not be created!")
            return TeamDTO.from_dbteam(new_team)   
        except SQLAlchemyError as e:
            # Log the error and handle it
            logger.error(f"Database error: {e}")
            raise DBException(f"Database error: {e}")
        finally:
            session.close()

    def update(self, team : TeamDTO):
        try:
            session = self.Session()
            team = DBTeam.update(session, team.id, **team.to_dict())
            # Example usage
            if not team:
                raise DBException("Team could not be updated!")
            return TeamDTO.from_dbteam(team)   
        except SQLAlchemyError as e:
            # Log the error and handle it
            logger.error(f"Database error: {e}")
            raise DBException(f"Database error: {e}")
        finally:
            session.close()


    def addPlayers(self, team_id, player_ids):
        try:
            session = self.Session()
            team = DBTeam.addPlayers(session, team_id, player_ids)
            # Example usage
            if not team:
                raise DBException("Team could not be updated!")
            return TeamDTO.from_dbteam(team)   
        except SQLAlchemyError as e:
            # Log the error and handle it
            logger.error(f"Database error: {e}")
            raise DBException(f"Database error: {e}")
        finally:
            session.close()

    def delete(self, team_id):
        try:
            session = self.Session()
            DBTeam.delete(session, team_id) 
        except SQLAlchemyError as e:
            # Log the error and handle it
            logger.error(f"Database error: {e}")
            raise DBException(f"Database error: {e}")
        finally:
            session.close()

    def get(self, team_id):
        try:
            session = self.Session()
            team = session.query(DBTeam).filter_by(id=team_id).first()
            # Example usage
            if not team:
                raise DBException("Team could not be found!")
            return TeamDTO.from_dbteam(team)   
        except SQLAlchemyError as e:
            # Log the error and handle it
            logger.error(f"Database error: {e}")
            raise DBException(f"Database error: {e}")
        finally:
            session.close()