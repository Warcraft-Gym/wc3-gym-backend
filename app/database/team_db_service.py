import logging

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.database.abstract_database_service import AbstractDatabaseService
from app.exceptions import DBException
from app.models.team import DBTeam
from app.schemas.team import Team
from app.util.query_util import QueryUtil

logger = logging.getLogger(__name__)


class TeamDBService(AbstractDatabaseService):
    def add(self, team: Team):
        with self.get_session() as session:
            new_team = DBTeam.add(session, team.to_db_dict())
            if not new_team:
                raise DBException("Team could not be created!")
            return Team.from_dbteam(new_team)

    def update(self, team: Team):
        with self.get_session() as session:
            team = DBTeam.update(session, team.id, **team.to_db_dict())
            if not team:
                raise DBException("Team could not be updated!")
            return Team.from_dbteam(team)

    def update_icon(self, team_id, file):
        with self.get_session() as session:
            team = DBTeam.update_icon(session, team_id, file)
            if not team:
                raise DBException("Team icon could not be updated!")
            return Team.from_dbteam(team)

    def addPlayers(self, team_id, season_id, player_ids):
        with self.get_session() as session:
            team = DBTeam.addPlayers(session, team_id, season_id, player_ids)
            if not team:
                raise DBException("Team could not be updated!")
            return Team.from_dbteam(team)

    def removePlayers(self, team_id, season_id, player_ids):
        with self.get_session() as session:
            team = DBTeam.removePlayers(session, team_id, season_id, player_ids)
            if not team:
                raise DBException("Team could not be updated!")
            return Team.from_dbteam(team)

    def setCoaches(self, team_id, season_id, coach_ids):
        with self.get_session() as session:
            team = DBTeam.setCoaches(session, team_id, season_id, coach_ids)
            if not team:
                raise DBException("Team could not be updated!")
            return Team.from_dbteam(team)

    def delete(self, team_id):
        with self.get_session() as session:
            DBTeam.delete(session, team_id)

    def get(self, team_id):
        with self.get_session() as session:
            from app.models.relationships import DBTeamSeason

            # Eager load related entities, disable nested loading
            team = (
                session.scalars(
                    select(DBTeam)
                    .options(
                        joinedload(DBTeam.user_seasons).noload("*"),
                        joinedload(DBTeam.season_info).joinedload(DBTeamSeason.coach_1),
                        joinedload(DBTeam.season_info).joinedload(DBTeamSeason.coach_2),
                        joinedload(DBTeam.season_info).joinedload(DBTeamSeason.coach_3),
                    )
                    .where(DBTeam.id == team_id)
                )
                .unique()
                .first()
            )
            if not team:
                raise DBException("Team could not be found!")
            return Team.from_dbteam(team)

    def get_with_nested_users(self, team_id):
        with self.get_session() as session:
            from app.models.relationships import DBUserTeamSeason
            from app.models.user import DBUser

            # Eager load user_seasons and their users with w3c_stats and team_seasons (gnl_stats) with season info
            team = (
                session.scalars(
                    select(DBTeam)
                    .options(
                        joinedload(DBTeam.user_seasons)
                        .joinedload(DBUserTeamSeason.user)
                        .joinedload(DBUser.w3c_stats),
                        joinedload(DBTeam.user_seasons)
                        .joinedload(DBUserTeamSeason.user)
                        .joinedload(DBUser.team_seasons)
                        .joinedload(DBUserTeamSeason.season),
                        joinedload(DBTeam.user_seasons).noload(DBUserTeamSeason.team),
                        joinedload(DBTeam.season_info).noload("*"),
                    )
                    .where(DBTeam.id == team_id)
                )
                .unique()
                .first()
            )
            if not team:
                raise DBException("Team could not be found!")
            return Team.from_dbteam(team)

    def get_with_nested_users_by_season(self, team_id, season_id):
        """Get team with users filtered by specific season at database level"""
        with self.get_session() as session:
            from app.models.relationships import DBTeamSeason, DBUserTeamSeason
            from app.models.user import DBUser

            # Eager load only user_seasons for the specified season, including w3c_stats and team_seasons (gnl_stats) with season info
            team = (
                session.scalars(
                    select(DBTeam)
                    .options(
                        joinedload(
                            DBTeam.user_seasons.and_(
                                DBUserTeamSeason.season_id == season_id
                            )
                        )
                        .joinedload(DBUserTeamSeason.user)
                        .joinedload(DBUser.w3c_stats),
                        joinedload(
                            DBTeam.user_seasons.and_(
                                DBUserTeamSeason.season_id == season_id
                            )
                        )
                        .joinedload(DBUserTeamSeason.user)
                        .joinedload(DBUser.team_seasons)
                        .joinedload(DBUserTeamSeason.season),
                        joinedload(DBTeam.user_seasons).noload(DBUserTeamSeason.team),
                        joinedload(
                            DBTeam.season_info.and_(
                                DBTeam.season_info.any(season_id=season_id)
                            )
                        ).joinedload(DBTeamSeason.coach_1),
                        joinedload(
                            DBTeam.season_info.and_(
                                DBTeam.season_info.any(season_id=season_id)
                            )
                        ).joinedload(DBTeamSeason.coach_2),
                        joinedload(
                            DBTeam.season_info.and_(
                                DBTeam.season_info.any(season_id=season_id)
                            )
                        ).joinedload(DBTeamSeason.coach_3),
                    )
                    .where(DBTeam.id == team_id)
                )
                .unique()
                .first()
            )
            if not team:
                raise DBException("Team could not be found!")
            return Team.from_dbteam(team)

    def get_icon(self, team_id):
        with self.get_session() as session:
            team = session.get(DBTeam, team_id)
            if not team:
                raise DBException("Team could not be found!")
            return team.icon

    def search(self, query):
        with self.get_session() as session:
            result = []
            filter = QueryUtil.convertQueryToDBFilter(DBTeam, query)
            # Eager load related entities, disable nested loading
            teams = (
                session.scalars(
                    select(DBTeam)
                    .options(
                        joinedload(DBTeam.user_seasons).noload("*"),
                        joinedload(DBTeam.season_info).noload("*"),
                    )
                    .where(filter)
                )
                .unique()
                .all()
                if filter is not None
                else []
            )
            if not teams:
                logger.debug(f"No teams found by searchcriteria: {query}")
                return result
            for team in teams:
                result.append(Team.from_dbteam(team))
            return result

    def getAll(self):
        with self.get_session() as session:
            result = []
            # Eager load related entities, disable nested loading
            teams = (
                session.scalars(
                    select(DBTeam).options(
                        joinedload(DBTeam.user_seasons).noload("*"),
                        joinedload(DBTeam.season_info).noload("*"),
                    )
                )
                .unique()
                .all()
            )
            for team in teams:
                result.append(Team.from_dbteam(team))
            return result

    def getAll_basic(self):
        """Get all teams with basic info only (no users, no seasons)"""
        with self.get_session() as session:
            result = []
            # Explicitly prevent loading of all relationships
            from sqlalchemy.orm import noload

            teams = session.scalars(select(DBTeam).options(noload("*"))).unique().all()
            for team in teams:
                result.append(Team.from_dbteam(team))
            return result

    def getAll_by_season(self, season_id):
        """Get all teams for a season with season_info but without users"""
        with self.get_session() as session:
            result = []
            from sqlalchemy.orm import noload

            # Load season_info but not user_seasons
            teams = (
                session.scalars(
                    select(DBTeam)
                    .options(
                        noload(DBTeam.user_seasons),
                        joinedload(DBTeam.season_info).noload("*"),
                    )
                    .join(DBTeam.season_info)
                    .where(DBTeam.season_info.any(season_id=season_id))
                )
                .unique()
                .all()
            )
            for team in teams:
                result.append(Team.from_dbteam(team))
            return result

    def getAll_with_nested_users(self):
        with self.get_session() as session:
            from app.models.relationships import DBTeamSeason, DBUserTeamSeason
            from app.models.user import DBUser

            result = []
            # Eager load user_seasons and their users with w3c_stats and team_seasons (gnl_stats) with season info
            # Also eager load coaches from season_info
            teams = (
                session.scalars(
                    select(DBTeam).options(
                        joinedload(DBTeam.user_seasons)
                        .joinedload(DBUserTeamSeason.user)
                        .joinedload(DBUser.w3c_stats),
                        joinedload(DBTeam.user_seasons)
                        .joinedload(DBUserTeamSeason.user)
                        .joinedload(DBUser.team_seasons)
                        .joinedload(DBUserTeamSeason.season),
                        joinedload(DBTeam.user_seasons).noload(DBUserTeamSeason.team),
                        joinedload(DBTeam.season_info).joinedload(DBTeamSeason.coach_1),
                        joinedload(DBTeam.season_info).joinedload(DBTeamSeason.coach_2),
                        joinedload(DBTeam.season_info).joinedload(DBTeamSeason.coach_3),
                    )
                )
                .unique()
                .all()
            )
            for team in teams:
                result.append(Team.from_dbteam(team))
            return result
