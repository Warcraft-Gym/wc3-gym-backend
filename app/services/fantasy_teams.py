import logging

from sqlalchemy import select
from sqlalchemy.orm import joinedload, noload

from app.core.exceptions import NotFoundError
from app.core.query import QueryElement, QueryUtil
from app.models.fantasy_team import (
    FantasyTeam,
    FantasyTeamCreate,
    FantasyTeamPublic,
    FantasyTeamUpdate,
)
from app.models.relationships import DBFantasyTeamPlayer
from app.models.team import Team
from app.models.team_season import DBTeamSeason
from app.models.user import User
from app.services.base import BaseService

logger = logging.getLogger(__name__)


class FantasyTeamService(BaseService):
    def add(self, fantasy_team: FantasyTeamCreate) -> FantasyTeamPublic:
        with self.get_session() as session:
            fantasy_team = FantasyTeam.add(session, fantasy_team.model_dump())
            return FantasyTeamPublic.from_fantasy_team(fantasy_team)

    def update(
        self, fantasy_team_id: int, fantasy_team: FantasyTeamUpdate
    ) -> FantasyTeamPublic:
        with self.get_session() as session:
            fantasy_team = FantasyTeam.update(
                session,
                fantasy_team_id,
                **fantasy_team.model_dump(exclude_unset=True),
            )
            if not fantasy_team:
                raise NotFoundError("Fantasy Team not found")
            return FantasyTeamPublic.from_fantasy_team(fantasy_team)

    def delete(self, fantasy_team_id: int) -> None:
        with self.get_session() as session:
            FantasyTeam.delete(session, fantasy_team_id)

    def get(self, fantasy_team_id: int) -> FantasyTeamPublic:
        with self.get_session() as session:
            fteam = session.get(FantasyTeam, fantasy_team_id)
            if not fteam:
                raise NotFoundError("Fantasy Team not found")
            return FantasyTeamPublic.from_fantasy_team(fteam)

    # Every relation the list answer reads; the sub-collections stay empty
    _reduced_options = (
        joinedload(FantasyTeam.season).noload("*"),
        joinedload(FantasyTeam.drafted_team).noload("*"),
        joinedload(FantasyTeam.captain).noload("*"),
        joinedload(FantasyTeam.drafted_players)
        .joinedload(DBFantasyTeamPlayer.users)
        .noload("*"),
    )

    def getAll(self) -> list[FantasyTeamPublic]:
        with self.get_session() as session:
            result = []
            fteams = (
                session.scalars(select(FantasyTeam).options(*self._reduced_options))
                .unique()
                .all()
            )
            for fteam in fteams:
                result.append(FantasyTeamPublic.from_fantasy_team(fteam))
            return result

    def getAll_for_scoring(self) -> list[FantasyTeamPublic]:
        """The score recalculation reads the drafted team's seasons_info."""
        with self.get_session() as session:
            result = []
            fteams = (
                session.scalars(
                    select(FantasyTeam).options(
                        joinedload(FantasyTeam.season).noload("*"),
                        joinedload(FantasyTeam.captain).noload("*"),
                        joinedload(FantasyTeam.drafted_players)
                        .joinedload(DBFantasyTeamPlayer.users)
                        .noload("*"),
                        joinedload(FantasyTeam.drafted_team).noload(Team.user_seasons),
                        joinedload(FantasyTeam.drafted_team)
                        .selectinload(Team.season_info)
                        .options(
                            noload(DBTeamSeason.coach_1),
                            noload(DBTeamSeason.coach_2),
                            noload(DBTeamSeason.coach_3),
                            noload(DBTeamSeason.season),
                        ),
                    )
                )
                .unique()
                .all()
            )
            for fteam in fteams:
                result.append(FantasyTeamPublic.from_fantasy_team(fteam))
            return result

    def search(
        self, query: QueryElement | None, limit: int | None = None, offset: int = 0
    ) -> list[FantasyTeamPublic]:
        with self.get_session() as session:
            result = []
            filter = QueryUtil.convertQueryToDBFilter(FantasyTeam, query)
            if filter is None:
                logger.debug(f"No fantasy team found by searchcriteria: {query}")
                return result
            # Eager load only the relations the response model reads
            statement = (
                select(FantasyTeam).options(*self._reduced_options).where(filter)
            )
            if limit is not None or offset:
                # Offset paging is deterministic only with a fixed order
                statement = statement.order_by(FantasyTeam.id).offset(offset)
                if limit is not None:
                    statement = statement.limit(limit)
            fteams = session.scalars(statement).unique().all()
            if not fteams:
                logger.debug(f"No fantasy team found by searchcriteria: {query}")
                return result
            for fteam in fteams:
                result.append(FantasyTeamPublic.from_fantasy_team(fteam))
            return result

    def addPlayers(self, team_id: int, player_ids: list[int]) -> FantasyTeamPublic:
        with self.get_session() as session:
            fteam = session.get(FantasyTeam, team_id)
            if not fteam:
                raise NotFoundError(f"Fantasy Team not found by id: {team_id}")
            for user_id in player_ids:
                user = session.get(User, user_id)
                if not user:
                    raise NotFoundError(f"User not found by id: {user_id}")
                already_exists = (
                    session.get(
                        DBFantasyTeamPlayer,
                        {"fantasy_team_id": fteam.id, "user_id": user.id},
                    )
                    is not None
                )
                if not already_exists:
                    session.add(DBFantasyTeamPlayer(users=user, fantasy_team=fteam))
            session.flush()
            return FantasyTeamPublic.from_fantasy_team(fteam)

    def removePlayers(self, team_id: int, player_ids: list[int]) -> FantasyTeamPublic:
        with self.get_session() as session:
            fteam = session.get(FantasyTeam, team_id)
            if not fteam:
                raise NotFoundError(f"Fantasy Team not found by id: {team_id}")
            for user_id in player_ids:
                user = session.get(User, user_id)
                if not user:
                    raise NotFoundError(f"User not found by id: {user_id}")
                user_team = session.get(
                    DBFantasyTeamPlayer,
                    {"fantasy_team_id": team_id, "user_id": user.id},
                )
                if not user_team:
                    raise NotFoundError(
                        f"User not part of the fantasy team, user id: {user_id}"
                    )
                session.delete(user_team)
            session.flush()
            return FantasyTeamPublic.from_fantasy_team(fteam)

    def create_fantasy_team(self, team: FantasyTeamCreate) -> FantasyTeamPublic:
        return self.add(team)

    def update_fantasy_team(
        self, team_id: int, team: FantasyTeamUpdate
    ) -> FantasyTeamPublic:
        return self.update(team_id, team)

    def delete_fantasy_team(self, team_id: int) -> None:
        self.delete(team_id)

    def get_fantasy_team(self, team_id: int) -> FantasyTeamPublic:
        team_data = self.get(team_id)
        if not team_data:
            raise NotFoundError(f"Fantasy Team not found by Id: {team_id}")
        return team_data

    def getAll_fantasy_teams(self) -> list[FantasyTeamPublic]:
        return self.getAll()

    def search_fantasy_teams(
        self, query: QueryElement | None, limit: int | None = None, offset: int = 0
    ) -> list[FantasyTeamPublic]:
        return self.search(query, limit=limit, offset=offset)

    def addFantasyPlayers(self, team_id: int, players: list[int]) -> FantasyTeamPublic:
        return self.addPlayers(team_id, players)

    def removeFantasyPlayers(
        self, team_id: int, players: list[int]
    ) -> FantasyTeamPublic:
        return self.removePlayers(team_id, players)
