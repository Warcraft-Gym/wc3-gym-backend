import logging

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.exceptions import DBException, NotFoundException
from app.models.team import DBTeam
from app.schemas.team import Team
from app.services.base import BaseService
from app.services.users import UserService
from app.utils.query_util import QueryUtil

logger = logging.getLogger(__name__)


class TeamService(BaseService):
    def __init__(self, user_app_service: UserService):
        self.user_app_service = user_app_service

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
                raise NotFoundException("Team not found")
            return Team.from_dbteam(team)

    def update_icon(self, team_id, file):
        with self.get_session() as session:
            team = DBTeam.update_icon(session, team_id, file)
            if not team:
                raise NotFoundException("Team not found")
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
                raise NotFoundException("Team not found")
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
                raise NotFoundException("Team not found")
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
                raise NotFoundException("Team not found")
            return Team.from_dbteam(team)

    def get_icon(self, team_id):
        with self.get_session() as session:
            team = session.get(DBTeam, team_id)
            if not team:
                raise NotFoundException("Team not found")
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

    def create_team(self, team: Team):
        team.id = None
        return self.add(team)

    def update_team(self, team_id: int, team: Team):
        team.id = team_id
        return self.update(team)

    def update_team_icon(self, team_id: int, file):
        return self.update_icon(team_id, file)

    def delete_team(self, team_id: int):
        self.delete(team_id)

    def get_team(self, team_id: int):
        team_data = self.get(team_id)
        if not team_data:
            raise NotFoundException(f"Team not found by Id: {team_id}")
        return team_data

    def get_team_icon(self, team_id: int):
        return self.get_icon(team_id)

    def get_team_season(self, team_id: int, season_id):
        team_data = self.get_with_nested_users_by_season(team_id, season_id)
        if not team_data:
            raise NotFoundException(f"Team not found by Id: {team_id}")
        # Data is already filtered by season at database level
        return team_data

    def get_teams_season(self, season_id: int):
        teams_data = self.getAll_with_nested_users()
        result = []
        if teams_data:
            for team_data in teams_data:
                # filter users and season info based on season id
                season_info = [
                    s_inf
                    for s_inf in team_data.seasons_info
                    if s_inf.season_id == season_id
                ]
                if not season_info:
                    # team not part of the requested season
                    continue
                team_data.seasons_info = season_info
                season_player = team_data.player_by_season.get(season_id)
                team_data.player_by_season = {season_id: season_player}
                team_data.seasons_info = [
                    seasons_info
                    for seasons_info in team_data.seasons_info
                    if seasons_info.season_id == season_id
                ]
                result.append(team_data)
        return result

    def get_teams_season_basic(self, season_id: int):
        """Get teams for a season with season_info but without users (for list views)"""
        teams_data = self.getAll_by_season(season_id)
        result = []
        if teams_data:
            for team_data in teams_data:
                # Filter season_info to only include the requested season
                team_data.seasons_info = [
                    s_inf
                    for s_inf in team_data.seasons_info
                    if s_inf.season_id == season_id
                ]
                result.append(team_data)
        return result

    def syncW3CStatsTeam(self, team_id, season_id):
        team = self.get_team_season(team_id, season_id)
        users = team.player_by_season.get(season_id)
        sync_errors = []

        if users:
            for u in users:
                try:
                    self.user_app_service.updateW3CStats(u)
                except Exception as e:
                    # Log the error but continue syncing other players
                    error_msg = f"Failed to sync W3C stats for user {u.name} (BattleTag: {u.battleTag}): {e!s}"
                    sync_errors.append(error_msg)
                    print(error_msg)  # Log to console

        # Return the updated team data even if some players failed
        result = self.get_team_season(team_id, season_id)

        # If there were errors, log them but don't fail the whole operation
        if sync_errors:
            print(
                f"W3C sync completed with {len(sync_errors)} error(s) for team {team_id}"
            )

        return result
