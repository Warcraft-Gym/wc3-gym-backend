import logging

from sqlalchemy import ColumnElement, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, joinedload, noload, selectinload

from app.core.exceptions import NotFoundError
from app.core.query import QueryElement, QueryUtil
from app.models.season import Season
from app.models.team import Team, TeamCreate, TeamPublic, TeamUpdate
from app.models.team_season import DBTeamSeason
from app.models.user import User
from app.models.user_team_season import DBUserTeamSeason
from app.services import derived
from app.services.base import BaseService
from app.services.users import UserService

logger = logging.getLogger(__name__)


def _public(session: Session, team: Team) -> TeamPublic:
    """One team, with its standings derived from the series it played."""
    public = TeamPublic.from_team(team)
    derived.fill_standings(session, [public])
    return public


class TeamService(BaseService):
    def __init__(self, user_app_service: UserService) -> None:
        self.user_app_service = user_app_service

    def add(self, team: TeamCreate) -> TeamPublic:
        with self.get_session() as session:
            new_team = Team.add(session, team.model_dump())
            return _public(session, new_team)

    def update(self, team_id: int, team: TeamUpdate) -> TeamPublic:
        with self.get_session() as session:
            team = Team.update(session, team_id, **team.model_dump(exclude_unset=True))
            if not team:
                raise NotFoundError("Team not found")
            return _public(session, team)

    def update_icon(self, team_id: int, file: bytes) -> TeamPublic:
        with self.get_session() as session:
            team = Team.update_icon(session, team_id, file)
            if not team:
                raise NotFoundError("Team not found")
            return _public(session, team)

    def addPlayers(
        self, team_id: int, season_id: int, player_ids: list[int]
    ) -> TeamPublic:
        with self.get_session() as session:
            team = session.get(Team, team_id)
            if not team:
                raise Exception(f"Team not found by id: {team_id}")
            season = session.get(Season, season_id)
            if not season:
                raise Exception(f"Season not found by id: {season_id}")
            for user_id in player_ids:
                user = session.get(User, user_id)
                if not user:
                    raise Exception(f"User not found by id: {user_id}")
                already_exists = (
                    session.get(
                        DBUserTeamSeason,
                        {
                            "team_id": team.id,
                            "season_id": season_id,
                            "user_id": user.id,
                        },
                    )
                    is not None
                )
                if not already_exists:
                    session.add(DBUserTeamSeason(user=user, season=season, team=team))
            session.flush()
            return _public(session, team)

    def removePlayers(
        self, team_id: int, season_id: int, player_ids: list[int]
    ) -> TeamPublic:
        with self.get_session() as session:
            team = session.get(Team, team_id)
            if not team:
                raise Exception(f"Team not found by id: {team_id}")
            season = session.get(Season, season_id)
            if not season:
                raise Exception(f"Season not found by id: {season_id}")
            for user_id in player_ids:
                user = session.get(User, user_id)
                if not user:
                    raise Exception(f"User not found by id: {user_id}")
                user_team = session.get(
                    DBUserTeamSeason,
                    {"team_id": team_id, "season_id": season_id, "user_id": user.id},
                )
                if not user_team:
                    raise Exception(f"User not part of the team, user id: {user_id}")
                session.delete(user_team)
            session.flush()
            return _public(session, team)

    def setCoaches(
        self, team_id: int, season_id: int, coach_ids: list[int]
    ) -> TeamPublic:
        """Set coaches for a team in a season (up to 3)."""
        with self.get_session() as session:
            team = session.get(Team, team_id)
            if not team:
                raise Exception(f"Team not found by id: {team_id}")
            season = session.get(Season, season_id)
            if not season:
                raise Exception(f"Season not found by id: {season_id}")

            # Validate coach limit
            if len(coach_ids) > 3:
                raise Exception("Cannot assign more than 3 coaches per team per season")

            # Validate all users exist
            for user_id in coach_ids:
                user = session.get(User, user_id)
                if not user:
                    raise Exception(f"User not found by id: {user_id}")

            # Get or create team_season entry
            team_season = session.get(
                DBTeamSeason, {"team_id": team_id, "season_id": season_id}
            )

            if not team_season:
                team_season = DBTeamSeason(team_id=team_id, season_id=season_id)
                session.add(team_season)

            # Set coaches (pad with None if less than 3)
            team_season.coach_1_id = coach_ids[0] if len(coach_ids) > 0 else None
            team_season.coach_2_id = coach_ids[1] if len(coach_ids) > 1 else None
            team_season.coach_3_id = coach_ids[2] if len(coach_ids) > 2 else None

            session.flush()
            return _public(session, team)

    def delete(self, team_id: int) -> None:
        with self.get_session() as session:
            Team.delete(session, team_id)

    def get(self, team_id: int) -> TeamPublic:
        with self.get_session() as session:
            # Eager load related entities, disable nested loading
            team = (
                session.scalars(
                    select(Team)
                    .options(
                        joinedload(Team.user_seasons).noload("*"),
                        joinedload(Team.season_info).joinedload(DBTeamSeason.coach_1),
                        joinedload(Team.season_info).joinedload(DBTeamSeason.coach_2),
                        joinedload(Team.season_info).joinedload(DBTeamSeason.coach_3),
                    )
                    .where(Team.id == team_id)
                )
                .unique()
                .first()
            )
            if not team:
                raise NotFoundError("Team not found")
            return _public(session, team)

    def get_with_nested_users(self, team_id: int) -> TeamPublic:
        with self.get_session() as session:
            # Eager load user_seasons and their users with w3c_stats and team_seasons (gnl_stats) with season info
            team = (
                session.scalars(
                    select(Team)
                    .options(
                        joinedload(Team.user_seasons)
                        .joinedload(DBUserTeamSeason.user)
                        .joinedload(User.w3c_stats),
                        joinedload(Team.user_seasons)
                        .joinedload(DBUserTeamSeason.user)
                        .joinedload(User.team_seasons)
                        .joinedload(DBUserTeamSeason.season),
                        joinedload(Team.user_seasons).noload(DBUserTeamSeason.team),
                        joinedload(Team.season_info).noload("*"),
                    )
                    .where(Team.id == team_id)
                )
                .unique()
                .first()
            )
            if not team:
                raise NotFoundError("Team not found")
            return _public(session, team)

    def get_with_nested_users_by_season(
        self, team_id: int, season_id: int
    ) -> TeamPublic:
        """Get team with users filtered by specific season at database level"""
        with self.get_session() as session:
            # Eager load only user_seasons for the specified season, including w3c_stats and team_seasons (gnl_stats) with season info
            team = (
                session.scalars(
                    select(Team)
                    .options(
                        joinedload(
                            Team.user_seasons.and_(
                                DBUserTeamSeason.season_id == season_id
                            )
                        )
                        .joinedload(DBUserTeamSeason.user)
                        .joinedload(User.w3c_stats),
                        joinedload(
                            Team.user_seasons.and_(
                                DBUserTeamSeason.season_id == season_id
                            )
                        )
                        .joinedload(DBUserTeamSeason.user)
                        .joinedload(User.team_seasons)
                        .joinedload(DBUserTeamSeason.season),
                        joinedload(Team.user_seasons).noload(DBUserTeamSeason.team),
                        joinedload(
                            Team.season_info.and_(
                                Team.season_info.any(season_id=season_id)
                            )
                        ).joinedload(DBTeamSeason.coach_1),
                        joinedload(
                            Team.season_info.and_(
                                Team.season_info.any(season_id=season_id)
                            )
                        ).joinedload(DBTeamSeason.coach_2),
                        joinedload(
                            Team.season_info.and_(
                                Team.season_info.any(season_id=season_id)
                            )
                        ).joinedload(DBTeamSeason.coach_3),
                    )
                    .where(Team.id == team_id)
                )
                .unique()
                .first()
            )
            if not team:
                raise NotFoundError("Team not found")
            return _public(session, team)

    def get_icon(self, team_id: int) -> bytes | None:
        with self.get_session() as session:
            team = session.get(Team, team_id)
            if not team:
                raise NotFoundError("Team not found")
            return team.icon

    def search(
        self, query: QueryElement | None, limit: int | None = None, offset: int = 0
    ) -> list[TeamPublic]:
        return self._where(
            QueryUtil.convertQueryToDBFilter(Team, query), limit=limit, offset=offset
        )

    def find_by_name(self, name: str) -> list[TeamPublic]:
        return self._where(Team.name == name)

    def _where(
        self,
        filter: ColumnElement[bool] | None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[TeamPublic]:
        with self.get_session() as session:
            result: list[TeamPublic] = []
            # Eager load related entities, disable nested loading
            statement = (
                select(Team)
                .options(
                    # noload alone; a joined link table multiplies the rows
                    noload(Team.user_seasons),
                    selectinload(Team.season_info).options(
                        noload(DBTeamSeason.coach_1),
                        noload(DBTeamSeason.coach_2),
                        noload(DBTeamSeason.coach_3),
                        noload(DBTeamSeason.season),
                    ),
                )
                .where(filter)
            )
            if limit is not None or offset:
                # Offset paging is deterministic only with a fixed order
                statement = statement.order_by(Team.id).offset(offset)
                if limit is not None:
                    statement = statement.limit(limit)
            teams = (
                session.scalars(statement).unique().all() if filter is not None else []
            )
            if not teams:
                logger.debug(f"No teams found by searchcriteria: {filter}")
                return result
            for team in teams:
                result.append(TeamPublic.from_team(team))
            derived.fill_standings(session, result)
            return result

    def getAll(self, limit: int | None = None, offset: int = 0) -> list[TeamPublic]:
        with self.get_session() as session:
            result: list[TeamPublic] = []
            # Eager load related entities, disable nested loading
            statement = select(Team).options(
                # noload alone; a joined link table multiplies the rows
                noload(Team.user_seasons),
                selectinload(Team.season_info).options(
                    noload(DBTeamSeason.coach_1),
                    noload(DBTeamSeason.coach_2),
                    noload(DBTeamSeason.coach_3),
                    noload(DBTeamSeason.season),
                ),
            )
            if limit is not None or offset:
                # Offset paging is deterministic only with a fixed order
                statement = statement.order_by(Team.id).offset(offset)
                if limit is not None:
                    statement = statement.limit(limit)
            teams = session.scalars(statement).unique().all()
            for team in teams:
                result.append(TeamPublic.from_team(team))
            derived.fill_standings(session, result)
            return result

    def getAll_basic(
        self, limit: int | None = None, offset: int = 0
    ) -> list[TeamPublic]:
        """Get all teams with basic info only (no users, no seasons)"""
        with self.get_session() as session:
            result: list[TeamPublic] = []
            # Explicitly prevent loading of all relationships
            from sqlalchemy.orm import noload

            statement = select(Team).options(noload("*"))
            if limit is not None or offset:
                # Offset paging is deterministic only with a fixed order
                statement = statement.order_by(Team.id).offset(offset)
                if limit is not None:
                    statement = statement.limit(limit)
            teams = session.scalars(statement).unique().all()
            for team in teams:
                result.append(TeamPublic.from_team(team))
            derived.fill_standings(session, result)
            return result

    def getAll_by_season(
        self, season_id: int, limit: int | None = None, offset: int = 0
    ) -> list[TeamPublic]:
        """Get all teams for a season with season_info but without users"""
        with self.get_session() as session:
            result: list[TeamPublic] = []
            from sqlalchemy.orm import noload

            # An EXISTS, not a join: a join multiplies the rows a page counts
            statement = (
                select(Team)
                .options(
                    noload(Team.user_seasons),
                    joinedload(Team.season_info).noload("*"),
                )
                .where(Team.season_info.any(season_id=season_id))
            )
            if limit is not None or offset:
                # Offset paging is deterministic only with a fixed order
                statement = statement.order_by(Team.id).offset(offset)
                if limit is not None:
                    statement = statement.limit(limit)
            teams = session.scalars(statement).unique().all()
            for team in teams:
                result.append(TeamPublic.from_team(team))
            derived.fill_standings(session, result)
            return result

    def create_team(self, team: TeamCreate) -> TeamPublic:
        return self.add(team)

    def update_team(self, team_id: int, team: TeamUpdate) -> TeamPublic:
        return self.update(team_id, team)

    def update_team_icon(self, team_id: int, file: bytes) -> TeamPublic:
        return self.update_icon(team_id, file)

    def delete_team(self, team_id: int) -> None:
        self.delete(team_id)

    def get_team(self, team_id: int) -> TeamPublic:
        team_data = self.get(team_id)
        if not team_data:
            raise NotFoundError(f"Team not found by Id: {team_id}")
        return team_data

    def get_team_icon(self, team_id: int) -> bytes | None:
        return self.get_icon(team_id)

    def get_team_season(self, team_id: int, season_id: int) -> TeamPublic:
        team_data = self.get_with_nested_users_by_season(team_id, season_id)
        if not team_data:
            raise NotFoundError(f"Team not found by Id: {team_id}")
        # Data is already filtered by season at database level
        return team_data

    def get_teams_season(
        self, season_id: int, limit: int | None = None, offset: int = 0
    ) -> list[TeamPublic]:
        """The season's teams with the season's rosters and coaches.

        The season sits in the query, so only that season's link rows
        load. Roster and coach users answer empty signup_seasons, and
        coaches empty gnl_stats; no consumer reads them on this route.
        """
        with self.get_session() as session:
            result: list[TeamPublic] = []
            roster = Team.user_seasons.and_(DBUserTeamSeason.season_id == season_id)
            info = Team.season_info.and_(DBTeamSeason.season_id == season_id)
            coach_loads = (
                joinedload(info)
                .joinedload(coach)
                .options(
                    selectinload(User.w3c_stats),
                    noload(User.team_seasons),
                    noload(User.signup_seasons),
                )
                for coach in (
                    DBTeamSeason.coach_1,
                    DBTeamSeason.coach_2,
                    DBTeamSeason.coach_3,
                )
            )
            statement = (
                select(Team)
                .where(Team.season_info.any(DBTeamSeason.season_id == season_id))
                .options(
                    joinedload(roster)
                    .joinedload(DBUserTeamSeason.user)
                    .options(
                        selectinload(User.w3c_stats),
                        selectinload(User.team_seasons).joinedload(
                            DBUserTeamSeason.season
                        ),
                        noload(User.signup_seasons),
                    ),
                    joinedload(roster).noload(DBUserTeamSeason.team),
                    *coach_loads,
                )
            )
            if limit is not None or offset:
                # Offset paging is deterministic only with a fixed order
                statement = statement.order_by(Team.id).offset(offset)
                if limit is not None:
                    statement = statement.limit(limit)
            teams = session.scalars(statement).unique().all()
            for team in teams:
                result.append(TeamPublic.from_team(team))
            derived.fill_standings(session, result)
            return result

    def get_teams_season_basic(
        self, season_id: int, limit: int | None = None, offset: int = 0
    ) -> list[TeamPublic]:
        """Get teams for a season with season_info but without users (for list views)"""
        teams_data = self.getAll_by_season(season_id, limit=limit, offset=offset)
        result: list[TeamPublic] = []
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

    def syncW3CStatsTeam(self, team_id: int, season_id: int) -> TeamPublic:
        team = self.get_team_season(team_id, season_id)
        users = team.player_by_season.get(season_id)
        sync_errors: list[str] = []

        if users:
            for u in users:
                try:
                    self.user_app_service.updateW3CStats(u)
                except Exception as e:
                    # The error list goes to the client, so it stays fixed
                    reason = (
                        "Database error" if isinstance(e, SQLAlchemyError) else str(e)
                    )
                    error_msg = f"Failed to sync W3C stats for user {u.name} (BattleTag: {u.battleTag}): {reason}"
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
