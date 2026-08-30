import logging
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import joinedload, noload, selectinload
from sqlmodel import col

from app.core.db import Session, rel
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.query import QueryElement, QueryUtil
from app.models.relationships import DBTeamSeasonCoach
from app.models.season import Season
from app.models.team import Team, TeamCreate, TeamPublic, TeamUpdate
from app.models.team_season import DBTeamSeason
from app.models.user import User, UserPublic
from app.models.user_team_season import DBUserTeamSeason
from app.services import derived, discord_roles
from app.services.users import UserService

logger = logging.getLogger(__name__)


def _fill(session: OrmSession, teams: list[TeamPublic]) -> None:
    """The standings of every team, and the season record of every player."""
    derived.fill_standings(session, teams)
    derived.fill_gnl_stats(
        session,
        [
            player
            for team in teams
            for players in team.player_by_season.values()
            for player in players
        ],
    )


def _public(session: OrmSession, team: Team) -> TeamPublic:
    """One team, with its standings derived from the series it played."""
    public = TeamPublic.from_team(team)
    _fill(session, [public])
    return public


def _season_loads(season_id: int) -> list[Any]:
    """Loader options for one season of a team: roster, coaches and stats."""
    roster = rel(Team.user_seasons).and_(col(DBUserTeamSeason.season_id) == season_id)
    info = rel(Team.season_info).and_(col(DBTeamSeason.season_id) == season_id)
    stats = rel(User.team_seasons).and_(col(DBUserTeamSeason.season_id) == season_id)
    seats = rel(Team.coach_seasons).and_(col(DBTeamSeasonCoach.season_id) == season_id)
    return [
        joinedload(roster)
        .joinedload(rel(DBUserTeamSeason.user))
        .options(
            selectinload(rel(User.w3c_stats)),
            selectinload(stats),
            noload(rel(User.signup_seasons)),
        ),
        joinedload(roster).noload(rel(DBUserTeamSeason.team)),
        joinedload(info),
        joinedload(seats)
        .joinedload(rel(DBTeamSeasonCoach.user))
        .options(
            selectinload(rel(User.w3c_stats)),
            noload(rel(User.team_seasons)),
            noload(rel(User.signup_seasons)),
        ),
    ]


class TeamService:
    def __init__(self, user_app_service: UserService) -> None:
        self.user_app_service = user_app_service

    def add(self, team: TeamCreate) -> TeamPublic:
        with Session.begin() as session:
            new_team = Team.add(session, team.model_dump())
            return _public(session, new_team)

    def update(self, team_id: int, team: TeamUpdate) -> TeamPublic:
        with Session.begin() as session:
            row = Team.update(session, team_id, **team.model_dump(exclude_unset=True))
            if not row:
                raise NotFoundError("Team not found")
            return _public(session, row)

    def update_icon(self, team_id: int, file: bytes) -> TeamPublic:
        with Session.begin() as session:
            team = Team.update_icon(session, team_id, file)
            if not team:
                raise NotFoundError("Team not found")
            return _public(session, team)

    def add_players(
        self, team_id: int, season_id: int, player_ids: list[int]
    ) -> TeamPublic:
        with Session.begin() as session:
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
            public = _public(session, team)

        discord_roles.sync(player_ids)
        return public

    def remove_players(
        self, team_id: int, season_id: int, player_ids: list[int]
    ) -> TeamPublic:
        with Session.begin() as session:
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
            public = _public(session, team)

        discord_roles.sync(player_ids)
        return public

    def set_coaches(
        self, team_id: int, season_id: int, coach_ids: list[int]
    ) -> TeamPublic:
        """Replace the coaches a team has in a season. Any number of them."""
        with Session.begin() as session:
            team = session.get(Team, team_id)
            if not team:
                raise NotFoundError(f"Team not found by id: {team_id}")
            season = session.get(Season, season_id)
            if not season:
                raise NotFoundError(f"Season not found by id: {season_id}")

            for user_id in coach_ids:
                if not session.get(User, user_id):
                    raise NotFoundError(f"User not found by id: {user_id}")

            # A team fields a season even before it has a coach in it
            if not session.get(
                DBTeamSeason, {"team_id": team_id, "season_id": season_id}
            ):
                session.add(DBTeamSeason(team_id=team_id, season_id=season_id))

            before = {
                seat.user_id
                for seat in team.coach_seasons
                if seat.season_id == season_id
            }
            after = set(coach_ids)
            for user_id in before - after:
                session.delete(
                    session.get(
                        DBTeamSeasonCoach,
                        {
                            "team_id": team_id,
                            "season_id": season_id,
                            "user_id": user_id,
                        },
                    )
                )
            for user_id in after - before:
                session.add(
                    DBTeamSeasonCoach(
                        team_id=team_id, season_id=season_id, user_id=user_id
                    )
                )

            session.flush()
            # The rows were written by id, so the team reads its coaches again
            session.expire(team, ["coach_seasons"])
            public = _public(session, team)

        # Discord mirrors the database, and the chip says what the guild lacks
        discord_roles.sync(before | after)
        public.discord_role_missing = [
            account.discord_id
            for account in discord_roles.report(after)
            if account.missing
        ]
        return public

    def coach_seat(self, discord_id: str, season: str | None) -> tuple[int, int] | None:
        """The team and season this Discord account coaches now, or None.

        The season is the `current_gnl_season` setting, or the newest season,
        as the admin pages resolve it.
        """
        with Session.begin() as session:
            season_id = (
                int(season)
                if season and season.isdigit()
                else session.scalar(select(func.max(col(Season.id))))
            )
            if season_id is None:
                return None
            seat = session.execute(
                select(col(DBTeamSeasonCoach.team_id), col(DBTeamSeasonCoach.season_id))
                .join(User, col(DBTeamSeasonCoach.user_id) == col(User.id))
                .where(
                    col(User.discordId) == discord_id,
                    col(DBTeamSeasonCoach.season_id) == season_id,
                )
            ).first()
            return (seat.team_id, seat.season_id) if seat else None

    def delete(self, team_id: int) -> None:
        with Session.begin() as session:
            Team.delete(session, team_id)

    def get(self, team_id: int) -> TeamPublic:
        with Session.begin() as session:
            # Eager load related entities, disable nested loading
            team = (
                session.scalars(
                    select(Team)
                    .options(
                        joinedload(rel(Team.user_seasons)).noload("*"),
                        joinedload(rel(Team.coach_seasons)).joinedload(
                            rel(DBTeamSeasonCoach.user)
                        ),
                    )
                    .where(col(Team.id) == team_id)
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
        with Session.begin() as session:
            team = (
                session.scalars(
                    select(Team)
                    .where(col(Team.id) == team_id)
                    .options(*_season_loads(season_id))
                )
                .unique()
                .first()
            )
            if not team:
                raise NotFoundError("Team not found")
            return _public(session, team)

    def get_icon(self, team_id: int) -> bytes | None:
        with Session.begin() as session:
            team = session.get(Team, team_id)
            if not team:
                raise NotFoundError("Team not found")
            return team.icon

    def search(
        self, query: QueryElement | None, limit: int | None = None, offset: int = 0
    ) -> list[TeamPublic]:
        return self._where(
            QueryUtil.convert_query_to_db_filter(Team, query),
            limit=limit,
            offset=offset,
        )

    def _where(
        self,
        filter: ColumnElement[bool] | None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[TeamPublic]:
        if filter is None:
            return []
        with Session.begin() as session:
            result: list[TeamPublic] = []
            # Eager load related entities, disable nested loading
            statement = (
                select(Team)
                .options(
                    # noload alone; a joined link table multiplies the rows
                    noload(rel(Team.user_seasons)),
                    noload(rel(Team.coach_seasons)),
                    selectinload(rel(Team.season_info)),
                )
                .where(filter)
            )
            if limit is not None or offset:
                # Offset paging is deterministic only with a fixed order
                statement = statement.order_by(col(Team.id)).offset(offset)
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
            _fill(session, result)
            return result

    def get_all(self, limit: int | None = None, offset: int = 0) -> list[TeamPublic]:
        with Session.begin() as session:
            result: list[TeamPublic] = []
            # Eager load related entities, disable nested loading
            statement = select(Team).options(
                # noload alone; a joined link table multiplies the rows
                noload(rel(Team.user_seasons)),
                noload(rel(Team.coach_seasons)),
                selectinload(rel(Team.season_info)),
            )
            if limit is not None or offset:
                # Offset paging is deterministic only with a fixed order
                statement = statement.order_by(col(Team.id)).offset(offset)
                if limit is not None:
                    statement = statement.limit(limit)
            teams = session.scalars(statement).unique().all()
            for team in teams:
                result.append(TeamPublic.from_team(team))
            _fill(session, result)
            return result

    def get_all_basic(
        self, limit: int | None = None, offset: int = 0
    ) -> list[TeamPublic]:
        """Get all teams with basic info only (no users, no seasons)"""
        with Session.begin() as session:
            result: list[TeamPublic] = []
            # Explicitly prevent loading of all relationships
            statement = select(Team).options(noload("*"))
            if limit is not None or offset:
                # Offset paging is deterministic only with a fixed order
                statement = statement.order_by(col(Team.id)).offset(offset)
                if limit is not None:
                    statement = statement.limit(limit)
            teams = session.scalars(statement).unique().all()
            for team in teams:
                result.append(TeamPublic.from_team(team))
            _fill(session, result)
            return result

    def get_all_by_season(
        self, season_id: int, limit: int | None = None, offset: int = 0
    ) -> list[TeamPublic]:
        """Get all teams for a season with season_info but without users"""
        with Session.begin() as session:
            result: list[TeamPublic] = []
            # An EXISTS, not a join: a join multiplies the rows a page counts
            statement = (
                select(Team)
                .options(
                    noload(rel(Team.user_seasons)),
                    noload(rel(Team.coach_seasons)),
                    joinedload(rel(Team.season_info)).noload("*"),
                )
                .where(col(Team.season_info).any(season_id=season_id))
            )
            if limit is not None or offset:
                # Offset paging is deterministic only with a fixed order
                statement = statement.order_by(col(Team.id)).offset(offset)
                if limit is not None:
                    statement = statement.limit(limit)
            teams = session.scalars(statement).unique().all()
            for team in teams:
                result.append(TeamPublic.from_team(team))
            _fill(session, result)
            return result

    def get_teams_season(
        self, season_id: int, limit: int | None = None, offset: int = 0
    ) -> list[TeamPublic]:
        """The season's teams with the season's rosters and coaches.

        The season sits in the query, so only that season's link rows
        load. Roster and coach users answer empty signup_seasons, and
        coaches empty gnl_stats; no consumer reads them on this route.
        """
        with Session.begin() as session:
            result: list[TeamPublic] = []
            statement = (
                select(Team)
                .where(
                    col(Team.season_info).any(col(DBTeamSeason.season_id) == season_id)
                )
                .options(*_season_loads(season_id))
            )
            if limit is not None or offset:
                # Offset paging is deterministic only with a fixed order
                statement = statement.order_by(col(Team.id)).offset(offset)
                if limit is not None:
                    statement = statement.limit(limit)
            teams = session.scalars(statement).unique().all()
            for team in teams:
                result.append(TeamPublic.from_team(team))
            _fill(session, result)
            return result

    def get_teams_season_basic(
        self, season_id: int, limit: int | None = None, offset: int = 0
    ) -> list[TeamPublic]:
        """Get teams for a season with season_info but without users (for list views)"""
        teams_data = self.get_all_by_season(season_id, limit=limit, offset=offset)
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

    def season_players(self, team_id: int, season_id: int) -> list[UserPublic]:
        """The players this team fielded in this season."""
        team = self.get_with_nested_users_by_season(team_id, season_id)
        return team.player_by_season.get(season_id) or []
