import logging
from sqlalchemy.orm import joinedload
from src.database.abstract_database_service import AbstractDatabaseService
from src.database.model.DBFantasyTeam import DBFantasyTeam
from src.database.model.DBRelationships import DBFantasyTeamPlayer
from custom_exceptions import DBException
from src.util.query_util import QueryUtil
from src.dtos.fantasy_team_dto import FantasyTeamDTO

logger = logging.getLogger(__name__)

class FantasyTeamDBService(AbstractDatabaseService):

    def add(self, fantasy_team : FantasyTeamDTO):
        with self.get_session() as session:
            fantasy_team = DBFantasyTeam.add(session, fantasy_team.to_db_dict())
            if not fantasy_team:
                raise DBException("FantasyTeam could not be created!")
            return FantasyTeamDTO.from_dbfantasyteam(fantasy_team)

    def update(self, fantasy_team: FantasyTeamDTO):
        with self.get_session() as session:
            fantasy_team = DBFantasyTeam.update(session, fantasy_team.id, **fantasy_team.to_db_dict())
            if not fantasy_team:
                raise DBException("Fantasy Team could not be updated!")
            return FantasyTeamDTO.from_dbfantasyteam(fantasy_team)

    def delete(self, fantasy_team_id):
        with self.get_session() as session:
            DBFantasyTeam.delete(session, fantasy_team_id)

    def get(self, fantasy_team_id):
        with self.get_session() as session:
            fteam = session.query(DBFantasyTeam).filter_by(id=fantasy_team_id).first()
            if not fteam:
                raise DBException("Fantasy Team could not be found")
            return FantasyTeamDTO.from_dbfantasyteam(fteam)

    def getAll(self):
        with self.get_session() as session:
            result = []
            fteams = DBFantasyTeam.getAll(session)
            for fteam in fteams:
                result.append(FantasyTeamDTO.from_dbfantasyteam(fteam))
            return result

    def search(self, query):
        with self.get_session() as session:
            result = []
            filter = QueryUtil.convertQueryToDBFilter(DBFantasyTeam, query)
            if filter is None:
                logger.debug(f"No fantasy team found by searchcriteria: {query}")
                return result
            # Eager load only the relations the DTO reads
            fteams = session.query(DBFantasyTeam)\
                .options(
                    joinedload(DBFantasyTeam.season).noload('*'),
                    joinedload(DBFantasyTeam.drafted_team).noload('*'),
                    joinedload(DBFantasyTeam.captain).noload('*'),
                    joinedload(DBFantasyTeam.drafted_players).joinedload(DBFantasyTeamPlayer.users).noload('*'),
                )\
                .filter(filter).all()
            if not fteams:
                logger.debug(f"No fantasy team found by searchcriteria: {query}")
                return result
            for fteam in fteams:
                result.append(FantasyTeamDTO.from_dbfantasyteam(fteam))
            return result

    def addPlayers(self, team_id, player_ids):
        with self.get_session() as session:
            fteam = DBFantasyTeam.addPlayers(session, team_id, player_ids)
            if not fteam:
                raise DBException("Fantasy Team could not be updated!")
            return FantasyTeamDTO.from_dbfantasyteam(fteam)

    def removePlayers(self, team_id, player_ids):
        with self.get_session() as session:
            team = DBFantasyTeam.removePlayers(session, team_id, player_ids)
            if not team:
                raise DBException("Fantasy Team could not be updated!")
            return FantasyTeamDTO.from_dbfantasyteam(team)
