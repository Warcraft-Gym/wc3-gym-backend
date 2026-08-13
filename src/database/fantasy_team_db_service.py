import logging

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from custom_exceptions import DBException
from src.database.abstract_database_service import AbstractDatabaseService
from src.models.fantasy_team import DBFantasyTeam
from src.models.relationships import DBFantasyTeamPlayer
from src.schemas.fantasy_team import FantasyTeam
from src.util.query_util import QueryUtil

logger = logging.getLogger(__name__)


class FantasyTeamDBService(AbstractDatabaseService):
    def add(self, fantasy_team: FantasyTeam):
        with self.get_session() as session:
            fantasy_team = DBFantasyTeam.add(session, fantasy_team.to_db_dict())
            if not fantasy_team:
                raise DBException("FantasyTeam could not be created!")
            return FantasyTeam.from_dbfantasyteam(fantasy_team)

    def update(self, fantasy_team: FantasyTeam):
        with self.get_session() as session:
            fantasy_team = DBFantasyTeam.update(
                session, fantasy_team.id, **fantasy_team.to_db_dict()
            )
            if not fantasy_team:
                raise DBException("Fantasy Team could not be updated!")
            return FantasyTeam.from_dbfantasyteam(fantasy_team)

    def delete(self, fantasy_team_id):
        with self.get_session() as session:
            DBFantasyTeam.delete(session, fantasy_team_id)

    def get(self, fantasy_team_id):
        with self.get_session() as session:
            fteam = session.get(DBFantasyTeam, fantasy_team_id)
            if not fteam:
                raise DBException("Fantasy Team could not be found")
            return FantasyTeam.from_dbfantasyteam(fteam)

    def getAll(self):
        with self.get_session() as session:
            result = []
            fteams = DBFantasyTeam.getAll(session)
            for fteam in fteams:
                result.append(FantasyTeam.from_dbfantasyteam(fteam))
            return result

    def search(self, query):
        with self.get_session() as session:
            result = []
            filter = QueryUtil.convertQueryToDBFilter(DBFantasyTeam, query)
            if filter is None:
                logger.debug(f"No fantasy team found by searchcriteria: {query}")
                return result
            # Eager load only the relations the DTO reads
            fteams = (
                session.scalars(
                    select(DBFantasyTeam)
                    .options(
                        joinedload(DBFantasyTeam.season).noload("*"),
                        joinedload(DBFantasyTeam.drafted_team).noload("*"),
                        joinedload(DBFantasyTeam.captain).noload("*"),
                        joinedload(DBFantasyTeam.drafted_players)
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
                result.append(FantasyTeam.from_dbfantasyteam(fteam))
            return result

    def addPlayers(self, team_id, player_ids):
        with self.get_session() as session:
            fteam = DBFantasyTeam.addPlayers(session, team_id, player_ids)
            if not fteam:
                raise DBException("Fantasy Team could not be updated!")
            return FantasyTeam.from_dbfantasyteam(fteam)

    def removePlayers(self, team_id, player_ids):
        with self.get_session() as session:
            team = DBFantasyTeam.removePlayers(session, team_id, player_ids)
            if not team:
                raise DBException("Fantasy Team could not be updated!")
            return FantasyTeam.from_dbfantasyteam(team)
