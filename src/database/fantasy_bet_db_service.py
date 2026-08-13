import logging
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from src.database.abstract_database_service import AbstractDatabaseService
from src.models.fantasy_bet import DBFantasyBet
from src.models.series import DBSeries
from custom_exceptions import DBException
from src.util.query_util import QueryUtil
from src.schemas.fantasy_bet import FantasyBet

logger = logging.getLogger(__name__)

class FantasyBetDBService(AbstractDatabaseService):

    def add(self, fantasy_bet : FantasyBet):
        with self.get_session() as session:
            fbet = DBFantasyBet.add(session, fantasy_bet.to_db_dict())
            if not fbet:
                raise DBException("FantasyBet could not be created!")
            return FantasyBet.from_dbfantasybet(fbet)

    def update(self, fantasy_bet: FantasyBet):
        with self.get_session() as session:
            fantasy_bet = DBFantasyBet.update(session, fantasy_bet.id, **fantasy_bet.to_db_dict())
            if not fantasy_bet:
                raise DBException("Fantasy Bet could not be updated!")
            return FantasyBet.from_dbfantasybet(fantasy_bet)

    def delete(self, fantasy_bet_id):
        with self.get_session() as session:
            DBFantasyBet.delete(session, fantasy_bet_id)

    def get(self, fantasy_bet_id):
        with self.get_session() as session:
            fbet = session.get(DBFantasyBet, fantasy_bet_id)
            if not fbet:
                raise DBException("Fantasy Bet could not be found")
            return FantasyBet.from_dbfantasybet(fbet)

    def getAll(self):
        with self.get_session() as session:
            result = []
            fbet = DBFantasyBet.getAll(session)
            for single_fbet in fbet:
                result.append(FantasyBet.from_dbfantasybet(single_fbet))
            return result

    def search(self, query):
        with self.get_session() as session:
            result = []
            filter = QueryUtil.convertQueryToDBFilter(DBFantasyBet, query)
            if filter is None:
                logger.debug(f"No fantasy bets found by searchcriteria: {query}")
                return result
            # Eager load the relations that the DTO and the score service read.
            # noload('*') stops all other relations from loading, so every
            # relation that a caller reads must be listed here. The score
            # breakdown reads series.match.playday.
            fbets = session.scalars(
                select(DBFantasyBet)
                .options(
                    joinedload(DBFantasyBet.season).noload('*'),
                    joinedload(DBFantasyBet.user).noload('*'),
                    joinedload(DBFantasyBet.winner).noload('*'),
                    joinedload(DBFantasyBet.series).noload('*'),
                    joinedload(DBFantasyBet.series).joinedload(DBSeries.player1).noload('*'),
                    joinedload(DBFantasyBet.series).joinedload(DBSeries.player2).noload('*'),
                    joinedload(DBFantasyBet.series).joinedload(DBSeries.match).noload('*'),
                )
                .where(filter)
            ).unique().all()
            if not fbets:
                logger.debug(f"No fantasy bets found by searchcriteria: {query}")
                return result
            for fbet in fbets:
                result.append(FantasyBet.from_dbfantasybet(fbet))
            return result
