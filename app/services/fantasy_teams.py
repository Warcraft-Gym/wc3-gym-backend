import logging

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.exceptions import NotFoundException
from app.models.fantasy_team import (
    FantasyTeam,
    FantasyTeamCreate,
    FantasyTeamPublic,
    FantasyTeamUpdate,
)
from app.models.relationships import DBFantasyTeamPlayer
from app.services.base import BaseService
from app.utils.query_util import QueryElement, QueryUtil

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
                raise NotFoundException("Fantasy Team not found")
            return FantasyTeamPublic.from_fantasy_team(fantasy_team)

    def delete(self, fantasy_team_id: int) -> None:
        with self.get_session() as session:
            FantasyTeam.delete(session, fantasy_team_id)

    def get(self, fantasy_team_id: int) -> FantasyTeamPublic:
        with self.get_session() as session:
            fteam = session.get(FantasyTeam, fantasy_team_id)
            if not fteam:
                raise NotFoundException("Fantasy Team not found")
            return FantasyTeamPublic.from_fantasy_team(fteam)

    def getAll(self) -> list[FantasyTeamPublic]:
        with self.get_session() as session:
            result = []
            fteams = FantasyTeam.getAll(session)
            for fteam in fteams:
                result.append(FantasyTeamPublic.from_fantasy_team(fteam))
            return result

    def search(self, query: QueryElement | None) -> list[FantasyTeamPublic]:
        with self.get_session() as session:
            result = []
            filter = QueryUtil.convertQueryToDBFilter(FantasyTeam, query)
            if filter is None:
                logger.debug(f"No fantasy team found by searchcriteria: {query}")
                return result
            # Eager load only the relations the DTO reads
            fteams = (
                session.scalars(
                    select(FantasyTeam)
                    .options(
                        joinedload(FantasyTeam.season).noload("*"),
                        joinedload(FantasyTeam.drafted_team).noload("*"),
                        joinedload(FantasyTeam.captain).noload("*"),
                        joinedload(FantasyTeam.drafted_players)
                        .joinedload(DBFantasyTeamPlayer.users)
                        .noload("*"),
                    )
                    .where(filter)
                )
                .unique()
                .all()
            )
            if not fteams:
                logger.debug(f"No fantasy team found by searchcriteria: {query}")
                return result
            for fteam in fteams:
                result.append(FantasyTeamPublic.from_fantasy_team(fteam))
            return result

    def addPlayers(self, team_id: int, player_ids: list[int]) -> FantasyTeamPublic:
        with self.get_session() as session:
            fteam = FantasyTeam.addPlayers(session, team_id, player_ids)
            return FantasyTeamPublic.from_fantasy_team(fteam)

    def removePlayers(self, team_id: int, player_ids: list[int]) -> FantasyTeamPublic:
        with self.get_session() as session:
            team = FantasyTeam.removePlayers(session, team_id, player_ids)
            return FantasyTeamPublic.from_fantasy_team(team)

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
            raise NotFoundException(f"Fantasy Team not found by Id: {team_id}")
        return team_data

    def getAll_fantasy_teams(self) -> list[FantasyTeamPublic]:
        return self.getAll()

    def search_fantasy_teams(
        self, query: QueryElement | None
    ) -> list[FantasyTeamPublic]:
        return self.search(query)

    def addFantasyPlayers(self, team_id: int, players: list[int]) -> FantasyTeamPublic:
        return self.addPlayers(team_id, players)

    def removeFantasyPlayers(
        self, team_id: int, players: list[int]
    ) -> FantasyTeamPublic:
        return self.removePlayers(team_id, players)
