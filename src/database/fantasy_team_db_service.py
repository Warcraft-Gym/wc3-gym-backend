import logging
from src.database.abstract_database_service import AbstractDatabaseService
from src.database.model.DBFantasyBet import DBFantasyBet
from src.database.model.DBFantasyTeam import DBFantasyTeam
from sqlalchemy.exc import SQLAlchemyError
from custom_exceptions import DBException
from src.util.query_util import QueryUtil
from src.dtos.fantasy_bet_dto import FantasyBetDTO
from src.dtos.fantasy_team_dto import FantasyTeamDTO

logger = logging.getLogger(__name__)

class FantasyTeamDBService(AbstractDatabaseService):
     
    def add(self, fantasy_team : FantasyTeamDTO):
        try:
            session = self.Session()
            fantasy_team = DBFantasyTeam.add(session, fantasy_team.to_db_dict())
            if not fantasy_team:
                raise DBException("FantasyTeam could not be created!")
            return FantasyTeamDTO.from_dbfantasyteam(fantasy_team)
        except SQLAlchemyError as e:
            raise DBException(f"Database error: {e}")
        finally:
            session.close()
    
    def update(self, fantasy_team: FantasyTeamDTO):
        try:
            session = self.Session()
            fantasy_team = DBFantasyTeam.update(session, fantasy_team.id, **fantasy_team.to_db_dict())
            if not fantasy_team:
                raise DBException("Fantasy Team could not be updated!")
            return FantasyTeamDTO.from_dbfantasyteam(fantasy_team)
        except SQLAlchemyError as e:
            raise DBException(f"Database error: {e}")
        finally:
            session.close()

    def delete(self, fantasy_team_id):
        try:
            session = self.Session()
            DBFantasyTeam.delete(session, fantasy_team_id)
        except SQLAlchemyError as e:
            raise DBException(f"Database error: {e}")
        finally:
            session.close()

    def get(self, fantasy_team_id):
        try:
            session = self.Session()
            fteam = session.query(DBFantasyTeam).filter_by(id=fantasy_team_id).first()
            if not fteam:
                raise DBException("Fantasy Team could not be found")
            return FantasyTeamDTO.from_dbfantasyteam(fteam)
        except SQLAlchemyError as e:
            raise DBException(f"Database error: {e}")
        finally:
            session.close()

    def getAll(self):
        try:
            result = []
            session = self.Session()
            fteams = DBFantasyTeam.getAll(session)
            for fteam in fteams:
                result.append(FantasyTeamDTO.from_dbfantasyteam(fteam))
            return result
        except SQLAlchemyError as e:
                raise DBException(f"Database error: {e}")

    def search(self, query):
        with self.get_session() as session:
            try:
                result = []
                filter = QueryUtil.convertQueryToDBFilter(DBFantasyTeam, query)
                fteams = DBFantasyTeam.search(session, filter)
                if not fteams:
                    logger.debug(f"No fantasy team found by searchcriteria: {query}")
                    return result
                for fteam in fteams:
                    result.append(FantasyTeamDTO.from_dbfantasyteam(fteam))
                return result
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")
            
    def addPlayers(self, team_id, player_ids):
        with self.get_session() as session:
            try:
                fteam = DBFantasyTeam.addPlayers(session, team_id, player_ids)
                if not fteam:
                    raise DBException("Fantasy Team could not be updated!")
                return FantasyTeamDTO.from_dbfantasyteam(fteam)   
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")
            
    def removePlayers(self, team_id, player_ids):
        with self.get_session() as session:
            try:
                team = DBFantasyTeam.removePlayers(session, team_id, player_ids)
                if not team:
                    raise DBException("Fantasy Team could not be updated!")
                return FantasyTeamDTO.from_dbfantasyteam(team)   
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")