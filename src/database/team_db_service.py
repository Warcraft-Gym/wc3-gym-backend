import logging
from src.database.abstract_database_service import AbstractDatabaseService
from src.database.model.DBTeam import DBTeam
from sqlalchemy.exc import SQLAlchemyError
from custom_exceptions import DBException
from src.dtos.team_dto import TeamDTO
from src.util.query_util import QueryUtil

logger = logging.getLogger(__name__)

class TeamDBService(AbstractDatabaseService):
    def add(self, team : TeamDTO):
        with self.get_session() as session:
            try:
                new_team = DBTeam.add(session, team.to_db_dict())
                if not new_team:
                    raise DBException("Team could not be created!")
                return TeamDTO.from_dbteam(new_team)   
            except SQLAlchemyError as e:
                # Log the error and handle it
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def update(self, team : TeamDTO):
        with self.get_session() as session:
            try:
                team = DBTeam.update(session, team.id, **team.to_db_dict())
                if not team:
                    raise DBException("Team could not be updated!")
                return TeamDTO.from_dbteam(team)   
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def addPlayers(self, team_id, player_ids):
        with self.get_session() as session:
            try:
                team = DBTeam.addPlayers(session, team_id, player_ids)
                if not team:
                    raise DBException("Team could not be updated!")
                return TeamDTO.from_dbteam(team)   
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def removePlayers(self, team_id, player_ids):
        with self.get_session() as session:
            try:
                team = DBTeam.removePlayers(session, team_id, player_ids)
                if not team:
                    raise DBException("Team could not be updated!")
                return TeamDTO.from_dbteam(team)   
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def delete(self, team_id):
        with self.get_session() as session:
            try:
                DBTeam.delete(session, team_id) 
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")


    def get(self, team_id):
        with self.get_session() as session:
            try:
                team = session.query(DBTeam).filter_by(id=team_id).first()
                if not team:
                    raise DBException("Team could not be found!")
                return TeamDTO.from_dbteam(team)   
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def search(self, query):
        with self.get_session() as session:
            try:
                result = []
                filter = QueryUtil.convertQueryToDBFilter(DBTeam, query)
                teams = DBTeam.seach(session, filter)
                if not teams:
                    logger.debug(f"No teams found by searchcriteria: {query}")
                    return result
                for team in teams:
                    result.append(TeamDTO.from_dbteam(team))
                return result
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def getAll(self):
        with self.get_session() as session:
            try:
                result = []
                teams = DBTeam.getAll(session)
                for team in teams:
                    result.append(TeamDTO.from_dbteam(team))
                return result
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")