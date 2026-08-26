import logging
from typing import Any

from sqlalchemy import ColumnElement, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, noload, selectinload

from app.core.exceptions import BadRequestError, NotFoundError
from app.core.query import QueryElement, QueryUtil
from app.models.season import Season
from app.models.team import Team, TeamCreate, TeamPublic, TeamUpdate
from app.models.team_season import DBTeamSeason
from app.models.user import User
from app.models.user_team_season import DBUserTeamSeason
from app.models.w3c_stats import W3CSyncResult
from app.services import derived
from app.services.base import BaseService
from app.services.users import SYNC_MAX_AGE, UserService

logger = logging.getLogger(__name__)


def _public(session: Session, team: Team) -> TeamPublic:
    """One team, with its standings derived from the series it played."""
    public = TeamPublic.from_team(team)
    derived.fill_standings(session, [public])
    return public


def _season_loads(season_id: int) -> list[Any]:
    """Loader options for one season of a team: roster, coaches and stats."""
    roster = Team.user_seasons.and_(DBUserTeamSeason.season_id == season_id)
    info = Team.season_info.and_(DBTeamSeason.season_id == season_id)
    stats = User.team_seasons.and_(DBUserTeamSeason.season_id == season_id)
    coach_loads = (
        joinedload(info)
        .joinedload(coach)
        .options(
            selectinload(User.w3c_stats),
            noload(User.team_seasons),
            noload(User.signup_seasons),
        )
        for coach in (DBTeamSeason.coach_1, DBTeamSeason.coach_2, DBTeamSeason.coach_3)
    )
    return [
        joinedload(roster)
        .joinedload(DBUserTeamSeason.user)
        .options(
            selectinload(User.w3c_stats),
            selectinload(stats),
            noload(User.signup_seasons),
        ),
        joinedload(roster).noload(DBUserTeamSeason.team),
        *coach_loads,
    ]


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
                raise NotFoundError(f"Team not found by id: {team_id}")
            season = session.get(Season, season_id)
            if not season:
                raise NotFoundError(f"Season not found by id: {season_id}")
            for user_id in player_ids:
                user = session.get(User, user_id)
                if not user:
                    raise NotFoundError(f"User not found by id: {user_id}")
                try:
                    # The primary key decides: a duplicate link is already there
                    with session.begin_nested():
                        session.add(
                            DBUserTeamSeason(user=user, season=season, team=team)
                        )
                except IntegrityError:
                    logger.debug(f"User {user_id} is already in team {team_id}")
            session.flush()
            return _public(session, team)

    def removePlayers(
        self, team_id: int, season_id: int, player_ids: list[int]
    ) -> TeamPublic:
        with self.get_session() as session:
            team = session.get(Team, team_id)
            if not team:
                raise NotFoundError(f"Team not found by id: {team_id}")
            season = session.get(Season, season_id)
            if not season:
                raise NotFoundError(f"Season not found by id: {season_id}")
            for user_id in player_ids:
                user = session.get(User, user_id)
                if not user:
                    raise NotFoundError(f"User not found by id: {user_id}")
                user_team = session.get(
                    DBUserTeamSeason,
                    {"team_id": team_id, "season_id": season_id, "user_id": user.id},
                )
                if not user_team:
                    raise BadRequestError(
                        f"User not part of the team, user id: {user_id}"
                    )
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
                raise NotFoundError(f"Team not found by id: {team_id}")
            season = session.get(Season, season_id)
            if not season:
                raise NotFoundError(f"Season not found by id: {season_id}")

            # Validate coach limit
            if len(coach_ids) > 3:
                raise BadRequestError(
                    "Cannot assign more than 3 coaches per team per season"
                )

            # Validate all users exist
            for user_id in coach_ids:
                user = session.get(User, user_id)
                if not user:
                    raise NotFoundError(f"User not found by id: {user_id}")

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

    def get_with_nested_users_by_season(
        self, team_id: int, season_id: int
    ) -> TeamPublic:
        """One team with the season's roster, coaches and stats."""
        with self.get_session() as session:
            team = (
                session.scalars(
                    select(Team)
                    .where(Team.id == team_id)
                    .options(*_season_loads(season_id))
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
            statement = (
                select(Team)
                .where(Team.season_info.any(DBTeamSeason.season_id == season_id))
                .options(*_season_loads(season_id))
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

    def syncW3CStatsTeam(self, team_id: int, season_id: int) -> W3CSyncResult:
        team = self.get_with_nested_users_by_season(team_id, season_id)
        users = team.player_by_season.get(season_id) or []
        return self.user_app_service.syncW3CStatsUsers(users, SYNC_MAX_AGE)
