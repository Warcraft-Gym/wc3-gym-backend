import logging

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.core.exceptions import NotFoundError
from app.core.query import QueryElement, QueryUtil
from app.models.match import Match, MatchCreate, MatchPublic, MatchUpdate
from app.services import derived
from app.services.base import BaseService

logger = logging.getLogger(__name__)


class MatchService(BaseService):
    def add(self, match: MatchCreate) -> MatchPublic:
        with self.get_session() as session:
            match = Match.add(session, match.model_dump())
            public = MatchPublic.from_match(match)
            derived.fill_matches(session, [public])
            return public

    def update(self, match_id: int, match: MatchUpdate) -> MatchPublic:
        with self.get_session() as session:
            match = Match.update(
                session, match_id, **match.model_dump(exclude_unset=True)
            )
            if not match:
                logger.error("Match could not be updated!")
                raise NotFoundError("Match not found")
            public = MatchPublic.from_match(match)
            derived.fill_matches(session, [public])
            return public

    def delete(self, match_id: int) -> None:
        with self.get_session() as session:
            Match.delete(session, match_id)

    def get(self, match_id: int) -> MatchPublic:
        with self.get_session() as session:
            # Eager load related entities, disable nested loading
            match = (
                session.scalars(
                    select(Match)
                    .options(
                        joinedload(Match.team1).noload("*"),
                        joinedload(Match.team2).noload("*"),
                        joinedload(Match.season).noload("*"),
                        joinedload(Match.fixed_map),
                    )
                    .where(Match.id == match_id)
                    .limit(1)
                )
                .unique()
                .first()
            )
            if not match:
                logger.error("Match could not be found!")
                raise NotFoundError("Match not found")
            public = MatchPublic.from_match_with_season(match)
            derived.fill_matches(session, [public])
            return public

    def search(
        self, query: QueryElement | None, limit: int | None = None, offset: int = 0
    ) -> list[MatchPublic]:
        with self.get_session() as session:
            result: list[MatchPublic] = []
            filter = QueryUtil.convertQueryToDBFilter(Match, query)
            # Eager load only what we need, explicitly disable other relationships
            statement = (
                select(Match)
                .options(
                    joinedload(Match.team1).noload("*"),
                    joinedload(Match.team2).noload("*"),
                    joinedload(Match.season).noload("*"),
                    joinedload(Match.fixed_map),
                )
                .where(filter)
            )
            if limit is not None or offset:
                # Offset paging is deterministic only with a fixed order
                statement = statement.order_by(Match.id).offset(offset)
                if limit is not None:
                    statement = statement.limit(limit)
            matches = (
                session.scalars(statement).unique().all() if filter is not None else []
            )
            if not matches:
                logger.debug(f"No matches found by searchcriteria: {query}")
                return result
            for match in matches:
                result.append(MatchPublic.from_match(match))
            derived.fill_matches(session, result)
            return result

    def create_match(self, match: MatchCreate) -> MatchPublic:
        return self.add(match)

    def update_match(self, match_id: int, match: MatchUpdate) -> MatchPublic:
        return self.update(match_id, match)

    def delete_match(self, match_id: int) -> None:
        self.delete(match_id)

    def get_match(self, match_id: int) -> MatchPublic:
        match_data = self.get(match_id)
        if not match_data:
            raise NotFoundError(f"Match not found by Id: {match_id}")
        return match_data
