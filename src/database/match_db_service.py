import logging
from src.database.abstract_database_service import AbstractDatabaseService
from src.database.model.DBMatch import DBMatch
from sqlalchemy.orm import joinedload
from custom_exceptions import DBException
from src.util.query_util import QueryUtil
from src.dtos.match_dto import MatchDTO

logger = logging.getLogger(__name__)

class MatchDBService(AbstractDatabaseService):
    def add(self, match: MatchDTO):
        with self.get_session() as session:
            match = DBMatch.add(session, match.to_db_dict())
            if not match:
                logger.error("Match could not be created!")
                raise DBException("Match could not be created!")
            return MatchDTO.from_dbmatch(match)

    def update(self, match_id, match: MatchDTO):
        with self.get_session() as session:
            match = DBMatch.update(session, match_id, **match.to_db_dict())
            if not match:
                logger.error("Match could not be updated!")
                raise DBException("Match could not be updated!")
            return MatchDTO.from_dbmatch(match)

    def delete(self, match_id):
        with self.get_session() as session:
            DBMatch.delete(session, match_id)

    def get(self, match_id):
        with self.get_session() as session:
            # Eager load related entities, disable nested loading
            match = session.query(DBMatch)\
                .options(
                    joinedload(DBMatch.team1).noload('*'),
                    joinedload(DBMatch.team2).noload('*'),
                    joinedload(DBMatch.season).noload('*'),
                    joinedload(DBMatch.fixed_map)
                )\
                .filter_by(id=match_id).first()
            if not match:
                logger.error("Match could not be found!")
                raise DBException("Match could not be found!")
            return MatchDTO.from_dbmatch(match)

    def search(self, query):
        with self.get_session() as session:
            result = []
            filter = QueryUtil.convertQueryToDBFilter(DBMatch, query)
            # Eager load only what we need, explicitly disable other relationships
            matches = session.query(DBMatch)\
                .options(
                    joinedload(DBMatch.team1).noload('*'),
                    joinedload(DBMatch.team2).noload('*'),
                    joinedload(DBMatch.season).noload('*'),
                    joinedload(DBMatch.fixed_map)
                )\
                .filter(filter).all() if filter is not None else []
            if not matches:
                logger.debug(f"No matches found by searchcriteria: {query}")
                return result
            for match in matches:
                result.append(MatchDTO.from_dbmatch(match))
            return result
