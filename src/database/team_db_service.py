import logging
from src.database.abstract_database_service import AbstractDatabaseService
from src.database.model.DBTeam import DBTeam
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload
from custom_exceptions import DBException
from src.dtos.team_dto import TeamDTO
from src.util.query_util import QueryUtil

logger = logging.getLogger(__name__)

class TeamDBService(AbstractDatabaseService):
    def add(self, team : TeamDTO):
        with self.get_session() as session:
            try:
                new_team = DBTeam.add(session, team.to_db_dict())
                if not new_team:
                    raise DBException("Team could not be created!")
                return TeamDTO.from_dbteam(new_team)   
            except SQLAlchemyError as e:
                # Log the error and handle it
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def update(self, team : TeamDTO):
        with self.get_session() as session:
            try:
                team = DBTeam.update(session, team.id, **team.to_db_dict())
                if not team:
                    raise DBException("Team could not be updated!")
                return TeamDTO.from_dbteam(team)   
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")
    
    def update_icon(self, team_id, file):
        with self.get_session() as session:
            try:
                team = DBTeam.update_icon(session, team_id, file)
                if not team:
                    raise DBException("Team icon could not be updated!")
                return TeamDTO.from_dbteam(team)   
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def addPlayers(self, team_id, season_id, player_ids):
        with self.get_session() as session:
            try:
                team = DBTeam.addPlayers(session, team_id, season_id, player_ids)
                if not team:
                    raise DBException("Team could not be updated!")
                return TeamDTO.from_dbteam(team)   
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def removePlayers(self, team_id, season_id, player_ids):
        with self.get_session() as session:
            try:
                team = DBTeam.removePlayers(session, team_id, season_id, player_ids)
                if not team:
                    raise DBException("Team could not be updated!")
                return TeamDTO.from_dbteam(team)   
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def delete(self, team_id):
        with self.get_session() as session:
            try:
                DBTeam.delete(session, team_id) 
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")


    def get(self, team_id):
        with self.get_session() as session:
            try:
                # Eager load related entities, disable nested loading
                team = session.query(DBTeam)\
                    .options(
                        joinedload(DBTeam.user_seasons).noload('*'),
                        joinedload(DBTeam.season_info).noload('*')
                    )\
                    .filter_by(id=team_id).first()
                if not team:
                    raise DBException("Team could not be found!")
                return TeamDTO.from_dbteam(team)   
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def get_with_nested_users(self, team_id):
        with self.get_session() as session:
            try:
                from src.database.model.DBRelationships import DBUserTeamSeason
                from src.database.model.DBUser import DBUser
                # Eager load user_seasons and their users with w3c_stats (GNL stats are in user_seasons)
                team = session.query(DBTeam)\
                    .options(
                        joinedload(DBTeam.user_seasons).joinedload(DBUserTeamSeason.user).joinedload(DBUser.w3c_stats).noload('*'),
                        joinedload(DBTeam.user_seasons).noload(DBUserTeamSeason.team),
                        joinedload(DBTeam.user_seasons).noload(DBUserTeamSeason.season),
                        joinedload(DBTeam.season_info).noload('*')
                    )\
                    .filter_by(id=team_id).first()
                if not team:
                    raise DBException("Team could not be found!")
                return TeamDTO.from_dbteam(team)   
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def get_with_nested_users_by_season(self, team_id, season_id):
        """Get team with users filtered by specific season at database level"""
        with self.get_session() as session:
            try:
                from src.database.model.DBRelationships import DBUserTeamSeason
                from src.database.model.DBUser import DBUser
                # Eager load only user_seasons for the specified season
                team = session.query(DBTeam)\
                    .options(
                        joinedload(DBTeam.user_seasons.and_(DBUserTeamSeason.season_id == season_id))
                            .joinedload(DBUserTeamSeason.user)
                            .joinedload(DBUser.w3c_stats).noload('*'),
                        joinedload(DBTeam.user_seasons).noload(DBUserTeamSeason.team),
                        joinedload(DBTeam.user_seasons).noload(DBUserTeamSeason.season),
                        joinedload(DBTeam.season_info.and_(DBTeam.season_info.any(season_id=season_id))).noload('*')
                    )\
                    .filter_by(id=team_id).first()
                if not team:
                    raise DBException("Team could not be found!")
                return TeamDTO.from_dbteam(team)   
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def get_icon(self, team_id):
        with self.get_session() as session:
            try:
                team = session.query(DBTeam).filter_by(id=team_id).first()
                if not team:
                    raise DBException("Team could not be found!")
                return team.icon
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def search(self, query):
        with self.get_session() as session:
            try:
                result = []
                filter = QueryUtil.convertQueryToDBFilter(DBTeam, query)
                # Eager load related entities, disable nested loading
                teams = session.query(DBTeam)\
                    .options(
                        joinedload(DBTeam.user_seasons).noload('*'),
                        joinedload(DBTeam.season_info).noload('*')
                    )\
                    .filter(filter).all() if filter is not None else []
                if not teams:
                    logger.debug(f"No teams found by searchcriteria: {query}")
                    return result
                for team in teams:
                    result.append(TeamDTO.from_dbteam(team))
                return result
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def getAll(self):
        with self.get_session() as session:
            try:
                result = []
                # Eager load related entities, disable nested loading
                teams = session.query(DBTeam)\
                    .options(
                        joinedload(DBTeam.user_seasons).noload('*'),
                        joinedload(DBTeam.season_info).noload('*')
                    ).all()
                for team in teams:
                    result.append(TeamDTO.from_dbteam(team))
                return result
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def getAll_basic(self):
        """Get all teams with basic info only (no users, no seasons)"""
        with self.get_session() as session:
            try:
                result = []
                # Explicitly prevent loading of all relationships
                from sqlalchemy.orm import noload
                teams = session.query(DBTeam).options(noload('*')).all()
                for team in teams:
                    result.append(TeamDTO.from_dbteam(team))
                return result
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def getAll_by_season(self, season_id):
        """Get all teams for a season with season_info but without users"""
        with self.get_session() as session:
            try:
                result = []
                from sqlalchemy.orm import noload
                # Load season_info but not user_seasons
                teams = session.query(DBTeam)\
                    .options(
                        noload(DBTeam.user_seasons),
                        joinedload(DBTeam.season_info).noload('*')
                    )\
                    .join(DBTeam.season_info)\
                    .filter(DBTeam.season_info.any(season_id=season_id))\
                    .all()
                for team in teams:
                    result.append(TeamDTO.from_dbteam(team))
                return result
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def getAll_with_nested_users(self):
        with self.get_session() as session:
            try:
                from src.database.model.DBRelationships import DBUserTeamSeason
                from src.database.model.DBUser import DBUser
                result = []
                # Eager load user_seasons and their users with w3c_stats (GNL stats are in user_seasons)
                teams = session.query(DBTeam)\
                    .options(
                        joinedload(DBTeam.user_seasons).joinedload(DBUserTeamSeason.user).joinedload(DBUser.w3c_stats).noload('*'),
                        joinedload(DBTeam.user_seasons).noload(DBUserTeamSeason.team),
                        joinedload(DBTeam.user_seasons).noload(DBUserTeamSeason.season),
                        joinedload(DBTeam.season_info).noload('*')
                    ).all()
                for team in teams:
                    result.append(TeamDTO.from_dbteam(team))
                return result
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")