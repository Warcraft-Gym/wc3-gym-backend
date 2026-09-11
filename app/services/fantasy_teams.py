import logging

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import joinedload, noload
from sqlmodel import col

from app.core.db import Session, rel
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.query import QueryElement, QueryUtil
from app.models.fantasy_team import (
    FantasyTeam,
    FantasyTeamCreate,
    FantasyTeamPublic,
    FantasyTeamUpdate,
)
from app.models.relationships import DBFantasyTeamPlayer, DBUserSeasonSignup
from app.models.season import Season, tier_count
from app.models.team_season import DBTeamSeason
from app.models.user import User
from app.services import derived, discord_roles

logger = logging.getLogger(__name__)


def _check_grind(
    session: OrmSession, team_id: int | None, season_id: int | None
) -> None:
    """A grind pick names a team of a season that offers the pick."""
    if team_id is None or season_id is None:
        return
    season = session.get(Season, season_id)
    if season is None or not season.fantasy_grind:
        raise BadRequestError("This season offers no grind pick")
    if session.get(DBTeamSeason, {"team_id": team_id, "season_id": season_id}) is None:
        raise BadRequestError("The grind team is not a team of this season")


class FantasyTeamService:
    def check_roster(self, season_id: int, player_ids: list[int]) -> None:
        """A roster holds one signup from each tier the season cuts."""
        with Session.begin() as session:
            season = session.get(Season, season_id)
            if season is None:
                raise NotFoundError(f"Season not found by id: {season_id}")
            count = tier_count(season.fantasy_tier_cuts)
            if count == 0:
                raise BadRequestError("This season has no fantasy tiers yet")
            tiers = session.scalars(
                select(col(DBUserSeasonSignup.fantasy_tier)).where(
                    col(DBUserSeasonSignup.season_id) == season_id,
                    col(DBUserSeasonSignup.user_id).in_(player_ids),
                )
            ).all()
            if (
                len(player_ids) != count
                or len(tiers) != count
                or set(tiers) != set(range(1, count + 1))
            ):
                raise BadRequestError(
                    f"A fantasy team drafts one player from each of the {count} tiers"
                )

    def add(self, fantasy_team: FantasyTeamCreate) -> FantasyTeamPublic:
        with Session.begin() as session:
            _check_grind(session, fantasy_team.grind_team_id, fantasy_team.season_id)
            row = FantasyTeam.add(session, fantasy_team.model_dump())
            public = FantasyTeamPublic.from_fantasy_team(row)
            derived.fill_fantasy_teams(session, [public])

        # A captain earns the fantasy role, so the guild hears about the team
        discord_roles.sync([fantasy_team.captain_id])
        return public

    def update(
        self, fantasy_team_id: int, fantasy_team: FantasyTeamUpdate
    ) -> FantasyTeamPublic:
        with Session.begin() as session:
            row = FantasyTeam.update(
                session,
                fantasy_team_id,
                **fantasy_team.model_dump(exclude_unset=True),
            )
            if not row:
                raise NotFoundError("Fantasy Team not found")
            _check_grind(session, row.grind_team_id, row.season_id)
            public = FantasyTeamPublic.from_fantasy_team(row)
            derived.fill_fantasy_teams(session, [public])
            return public

    def delete(self, fantasy_team_id: int) -> None:
        with Session.begin() as session:
            FantasyTeam.delete(session, fantasy_team_id)

    def get(self, fantasy_team_id: int) -> FantasyTeamPublic:
        with Session.begin() as session:
            fteam = session.get(FantasyTeam, fantasy_team_id)
            if not fteam:
                raise NotFoundError("Fantasy Team not found")
            public = FantasyTeamPublic.from_fantasy_team(fteam)
            derived.fill_standings(session, [public.drafted_team])
            derived.fill_fantasy_teams(session, [public])
            return public

    # Every relation the list answer reads; the other sub-collections stay
    # empty. The drafted players carry their stats so the leaderboard shows
    # MMR and GNL record without one request per player.
    _reduced_options = (
        joinedload(rel(FantasyTeam.season)).noload("*"),
        joinedload(rel(FantasyTeam.drafted_team)).noload("*"),
        joinedload(rel(FantasyTeam.captain)).noload("*"),
        joinedload(rel(FantasyTeam.drafted_players))
        .joinedload(rel(DBFantasyTeamPlayer.users))
        .options(
            joinedload(rel(User.team_seasons)).noload("*"),
            joinedload(rel(User.w3c_stats)),
            noload("*"),
        ),
    )

    def get_all(
        self, limit: int | None = None, offset: int = 0
    ) -> tuple[list[FantasyTeamPublic], int]:
        """The teams, or one page of them, and the total row count."""
        with Session.begin() as session:
            total = session.scalar(select(func.count()).select_from(FantasyTeam)) or 0
            # Offset paging is deterministic only with a fixed order
            statement = (
                select(FantasyTeam)
                .options(*self._reduced_options)
                .order_by(col(FantasyTeam.id))
                .offset(offset)
                .limit(limit)
            )
            fteams = session.scalars(statement).unique().all()
            result = [FantasyTeamPublic.from_fantasy_team(fteam) for fteam in fteams]
            derived.fill_fantasy_teams(session, result)
            derived.fill_gnl_stats(
                session, [player for team in result for player in team.drafted_players]
            )
            return result, total

    def search(
        self, query: QueryElement | None, limit: int | None = None, offset: int = 0
    ) -> tuple[list[FantasyTeamPublic], int | None]:
        """The matching teams and, when a page is asked for, the total count."""
        with Session.begin() as session:
            filter = QueryUtil.convert_query_to_db_filter(FantasyTeam, query)
            if filter is None:
                logger.debug(f"No fantasy team found by searchcriteria: {query}")
                return [], None
            total = None
            if limit is not None or offset:
                total = session.scalar(
                    select(func.count()).select_from(FantasyTeam).where(filter)
                )
            # Offset paging is deterministic only with a fixed order
            statement = (
                select(FantasyTeam)
                .options(*self._reduced_options)
                .where(filter)
                .order_by(col(FantasyTeam.id))
                .offset(offset)
                .limit(limit)
            )
            fteams = session.scalars(statement).unique().all()
            result = [FantasyTeamPublic.from_fantasy_team(fteam) for fteam in fteams]
            derived.fill_fantasy_teams(session, result)
            derived.fill_gnl_stats(
                session, [player for team in result for player in team.drafted_players]
            )
            return result, total

    def add_players(self, team_id: int, player_ids: list[int]) -> FantasyTeamPublic:
        with Session.begin() as session:
            fteam = session.get(FantasyTeam, team_id)
            if not fteam:
                raise NotFoundError(f"Fantasy Team not found by id: {team_id}")
            for user_id in player_ids:
                user = session.get(User, user_id)
                if not user:
                    raise NotFoundError(f"User not found by id: {user_id}")
                try:
                    # The primary key decides: a duplicate link is already there
                    with session.begin_nested():
                        session.add(DBFantasyTeamPlayer(users=user, fantasy_team=fteam))
                except IntegrityError:
                    logger.debug(f"User {user_id} is already in fantasy team {team_id}")
            session.flush()
            public = FantasyTeamPublic.from_fantasy_team(fteam)
            derived.fill_fantasy_teams(session, [public])
            return public

    def remove_players(self, team_id: int, player_ids: list[int]) -> FantasyTeamPublic:
        with Session.begin() as session:
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
            public = FantasyTeamPublic.from_fantasy_team(fteam)
            derived.fill_fantasy_teams(session, [public])
            return public
