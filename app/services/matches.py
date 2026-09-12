import logging

from sqlalchemy import select
from sqlalchemy.orm import joinedload
from sqlmodel import col

from app.core.db import Session, rel
from app.core.exceptions import NotFoundError
from app.core.query import QueryElement, QueryUtil
from app.models.base import ident
from app.models.match import Match, MatchCreate, MatchPublic, MatchUpdate
from app.models.relationships import round_for
from app.services import derived

logger = logging.getLogger(__name__)


class MatchService:
    def add(self, match: MatchCreate) -> MatchPublic:
        with Session.begin() as session:
            data = match.model_dump()
            # A tie is played in the round its playday names
            data["round_id"] = ident(
                round_for(session, data["season_id"], data["playday"])
            )
            row = Match.add(session, data)
            public = MatchPublic.from_match(row)
            derived.fill_matches(session, [public])
            return public

    def update(self, match_id: int, match: MatchUpdate) -> MatchPublic:
        with Session.begin() as session:
            row = Match.update(
                session, match_id, **match.model_dump(exclude_unset=True)
            )
            if not row:
                logger.error("Match could not be updated!")
                raise NotFoundError("Match not found")
            if match.model_fields_set & {"season_id", "playday"}:
                # The tie moved, and its series follow the round key on update
                row.round_id = ident(round_for(session, row.season_id, row.playday))
                session.flush()
            public = MatchPublic.from_match(row)
            derived.fill_matches(session, [public])
            return public

    def delete(self, match_id: int) -> None:
        with Session.begin() as session:
            Match.delete(session, match_id)

    def get(self, match_id: int) -> MatchPublic:
        with Session.begin() as session:
            # Eager load related entities, disable nested loading
            match = (
                session.scalars(
                    select(Match)
                    .options(
                        joinedload(rel(Match.team1)).noload("*"),
                        joinedload(rel(Match.team2)).noload("*"),
                        joinedload(rel(Match.season)).noload("*"),
                        joinedload(rel(Match.fixed_map)),
                    )
                    .where(col(Match.id) == match_id)
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
        filter = QueryUtil.convert_query_to_db_filter(Match, query)
        if filter is None:
            return []
        with Session.begin() as session:
            # Offset paging is deterministic only with a fixed order
            statement = (
                select(Match)
                .options(
                    joinedload(rel(Match.team1)).noload("*"),
                    joinedload(rel(Match.team2)).noload("*"),
                    joinedload(rel(Match.season)).noload("*"),
                    joinedload(rel(Match.fixed_map)),
                )
                .where(filter)
                .order_by(col(Match.id))
                .offset(offset)
                .limit(limit)
            )
            matches = session.scalars(statement).unique().all()
            result = [MatchPublic.from_match(match) for match in matches]
            derived.fill_matches(session, result)
            return result
