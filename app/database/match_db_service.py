import logging

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.database.abstract_database_service import AbstractDatabaseService
from app.exceptions import DBException
from app.models.match import DBMatch
from app.schemas.match import Match
from app.util.query_util import QueryUtil

logger = logging.getLogger(__name__)


class MatchDBService(AbstractDatabaseService):
    def add(self, match: Match):
        with self.get_session() as session:
            match = DBMatch.add(session, match.to_db_dict())
            if not match:
                logger.error("Match could not be created!")
                raise DBException("Match could not be created!")
            return Match.from_dbmatch(match)

    def update(self, match_id, match: Match):
        with self.get_session() as session:
            match = DBMatch.update(session, match_id, **match.to_db_dict())
            if not match:
                logger.error("Match could not be updated!")
                raise DBException("Match could not be updated!")
            return Match.from_dbmatch(match)

    def delete(self, match_id):
        with self.get_session() as session:
            DBMatch.delete(session, match_id)

    def get(self, match_id):
        with self.get_session() as session:
            # Eager load related entities, disable nested loading
            match = (
                session.scalars(
                    select(DBMatch)
                    .options(
                        joinedload(DBMatch.team1).noload("*"),
                        joinedload(DBMatch.team2).noload("*"),
                        joinedload(DBMatch.season).noload("*"),
                        joinedload(DBMatch.fixed_map),
                    )
                    .where(DBMatch.id == match_id)
                    .limit(1)
                )
                .unique()
                .first()
            )
            if not match:
                logger.error("Match could not be found!")
                raise DBException("Match could not be found!")
            return Match.from_dbmatch(match)

    def search(self, query):
        with self.get_session() as session:
            result = []
            filter = QueryUtil.convertQueryToDBFilter(DBMatch, query)
            # Eager load only what we need, explicitly disable other relationships
            matches = (
                session.scalars(
                    select(DBMatch)
                    .options(
                        joinedload(DBMatch.team1).noload("*"),
                        joinedload(DBMatch.team2).noload("*"),
                        joinedload(DBMatch.season).noload("*"),
                        joinedload(DBMatch.fixed_map),
                    )
                    .where(filter)
                )
                .unique()
                .all()
                if filter is not None
                else []
            )
            if not matches:
                logger.debug(f"No matches found by searchcriteria: {query}")
                return result
            for match in matches:
                result.append(Match.from_dbmatch(match))
            return result
