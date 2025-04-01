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

class FantasyBetDBService(AbstractDatabaseService):

    def add(self, fantasy_bet : FantasyBetDTO):
        try:
            session = self.Session()
            fbet = DBFantasyBet.add(session, fantasy_bet.to_db_dict())
            if not fbet:
                raise DBException("FantasyBet could not be created!")
            return FantasyBetDTO.from_dbfantasybet(fbet)
        except SQLAlchemyError as e:
            raise DBException(f"Database error: {e}")
        finally:
            session.close()
    
    def update(self, fantasy_bet: FantasyBetDTO):
        try:
            session = self.Session()
            fantasy_bet = DBFantasyBet.update(session, fantasy_bet.id, **fantasy_bet.to_db_dict())
            if not fantasy_bet:
                raise DBException("Fantasy Bet could not be updated!")
            return FantasyBetDTO.from_dbfantasybet(fantasy_bet)
        except SQLAlchemyError as e:
            raise DBException(f"Database error: {e}")
        finally:
            session.close()

    def delete(self, fantasy_bet_id):
        try:
            session = self.Session()
            DBFantasyBet.delete(session, fantasy_bet_id)
        except SQLAlchemyError as e:
            raise DBException(f"Database error: {e}")
        finally:
            session.close()

    def get(self, fantasy_bet_id):
        try:
            session = self.Session()
            fbet = session.query(DBFantasyBet).filter_by(id=fantasy_bet_id).first()
            if not fbet:
                raise DBException("Fantasy Bet could not be found")
            return FantasyBetDTO.from_dbfantasybet(fbet)
        except SQLAlchemyError as e:
            raise DBException(f"Database error: {e}")
        finally:
            session.close()

    def getAll(self):
        try:
            result = []
            session = self.Session()
            fbet = DBFantasyBet.getAll(session)
            for single_fbet in fbet:
                result.append(FantasyBetDTO.from_dbfantasybet(single_fbet))
            return result
        except SQLAlchemyError as e:
                raise DBException(f"Database error: {e}")

    def search(self, query):
        with self.get_session() as session:
            try:
                result = []
                filter = QueryUtil.convertQueryToDBFilter(DBFantasyBet, query)
                fbets = DBFantasyBet.search(session, filter)
                if not fbets:
                    logger.debug(f"No fantasy bets found by searchcriteria: {query}")
                    return result
                for fbet in fbets:
                    result.append(FantasyBetDTO.from_dbfantasybet(fbet))
                return result
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")