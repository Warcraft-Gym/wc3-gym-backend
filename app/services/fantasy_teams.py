import logging
from collections.abc import Iterable, Sequence

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.orm.interfaces import ORMOption
from sqlmodel import col

from app.core.db import Session, rel
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.query import QueryElement, QueryUtil
from app.models.base import ident
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
from app.services.seasons import resolved_tiers
from app.services.users import load_players
from app.services.w3c_stats import fill, w3c_season

logger = logging.getLogger(__name__)


def _loads() -> tuple[ORMOption, ...]:
    """The rows a fantasy team answer reads off the team: its season, its
    drafted team and its members bare. A season is shared by every team of it,
    so selectin reads it once."""
    return (
        selectinload(rel(FantasyTeam.season)),
        joinedload(rel(FantasyTeam.drafted_team)),
        joinedload(rel(FantasyTeam.captain)),
        joinedload(rel(FantasyTeam.drafted_players)).joinedload(
            rel(DBFantasyTeamPlayer.users)
        ),
    )


def _list_loads() -> tuple[ORMOption, ...]:
    """The list rows add the team rows of the drafted players, so each carries
    his record in the season of his team; the captain carries none."""
    return (
        *_loads(),
        joinedload(rel(FantasyTeam.drafted_players))
        .joinedload(rel(DBFantasyTeamPlayer.users))
        .selectinload(rel(User.team_seasons)),
    )


def _publics(
    session: OrmSession, fteams: Sequence[FantasyTeam]
) -> list[FantasyTeamPublic]:
    """The answers of the teams: their scores, and the ladder summary and the
    season record of every member."""
    result = [FantasyTeamPublic.from_fantasy_team(fteam) for fteam in fteams]
    members = [
        user for team in result for user in (team.captain, *team.drafted_players)
    ]
    derived.fill_fantasy_teams(session, result)
    fill(session, members, w3c_season(session))
    derived.fill_gnl_stats(session, members)
    return result


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


def _check_roster(
    session: OrmSession, season_id: int | None, player_ids: list[int], complete: bool
) -> None:
    """A roster holds at most one signup from each tier the season cuts, and a
    complete one holds them all. The tier is the pin, else the band the MMR falls in."""
    season = session.get(Season, season_id) if season_id is not None else None
    if season is None:
        raise NotFoundError(f"Season not found by id: {season_id}")
    count = tier_count(season.fantasy_tier_cuts)
    if count == 0:
        raise BadRequestError("This season has no fantasy tiers yet")
    signups = session.scalars(
        select(DBUserSeasonSignup).where(
            col(DBUserSeasonSignup.season_id) == season_id,
            col(DBUserSeasonSignup.user_id).in_(player_ids),
        )
    ).all()
    resolved = resolved_tiers(session, season, signups)
    tiers = [resolved.get(player_id) for player_id in player_ids]
    wanted = set(range(1, count + 1))
    picked = set(tiers)
    if (
        len(tiers) != len(picked)
        or not picked <= wanted
        or (complete and picked != wanted)
    ):
        raise BadRequestError(
            f"A fantasy team drafts one player from each of the {count} tiers"
        )


def _add_players_in(
    session: OrmSession, fteam: FantasyTeam, player_ids: Iterable[int]
) -> None:
    """Link the players to the team; a link already there stays."""
    for user_id in player_ids:
        user = session.get(User, user_id)
        if not user:
            raise NotFoundError(f"User not found by id: {user_id}")
        try:
            # The primary key decides: a duplicate link is already there
            with session.begin_nested():
                session.add(DBFantasyTeamPlayer(users=user, fantasy_team=fteam))
        except IntegrityError:
            logger.debug(f"User {user_id} is already in fantasy team {fteam.id}")


def _remove_players_in(
    session: OrmSession, team_id: int, player_ids: Iterable[int]
) -> None:
    """Unlink the players from the team; each must be on it."""
    for user_id in player_ids:
        user_team = session.get(
            DBFantasyTeamPlayer, {"fantasy_team_id": team_id, "user_id": user_id}
        )
        if not user_team:
            raise NotFoundError(
                f"User not part of the fantasy team, user id: {user_id}"
            )
        session.delete(user_team)


class FantasyTeamService:
    def check_roster(self, season_id: int, player_ids: list[int]) -> None:
        """A roster holds one signup from each tier the season cuts."""
        with Session.begin() as session:
            _check_roster(session, season_id, player_ids, complete=True)

    def owner(self, fantasy_team_id: int) -> tuple[int, int]:
        """The captain and the season of the team, off its row."""
        with Session.begin() as session:
            fteam = session.get(FantasyTeam, fantasy_team_id)
            if not fteam:
                raise NotFoundError("Fantasy Team not found")
            return fteam.captain_id, fteam.season_id

    def add(self, fantasy_team: FantasyTeamCreate) -> FantasyTeamPublic:
        with Session.begin() as session:
            _check_grind(session, fantasy_team.grind_team_id, fantasy_team.season_id)
            team_id = ident(FantasyTeam.add(session, fantasy_team.model_dump()))

        # A captain earns the fantasy role, so the guild hears about the team
        discord_roles.sync([fantasy_team.captain_id])
        return self.get(team_id)

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
        return self.get(fantasy_team_id)

    def register(
        self, fantasy_team: FantasyTeamCreate, player_ids: list[int]
    ) -> FantasyTeamPublic:
        """The public registration: the captain's one team of the season,
        created or updated, and its roster set to `player_ids` when it names any."""
        with Session.begin() as session:
            fteam = session.scalars(
                select(FantasyTeam).where(
                    col(FantasyTeam.captain_id) == fantasy_team.captain_id,
                    col(FantasyTeam.season_id) == fantasy_team.season_id,
                )
            ).first()
            created = fteam is None
            if fteam is None:
                fteam = FantasyTeam.add(session, fantasy_team.model_dump())
            else:
                FantasyTeam.update_object(
                    session, fteam, **fantasy_team.model_dump(exclude_unset=True)
                )
            _check_grind(session, fteam.grind_team_id, fteam.season_id)
            team_id = ident(fteam)
            if player_ids:
                current = set(
                    session.scalars(
                        select(col(DBFantasyTeamPlayer.user_id)).where(
                            col(DBFantasyTeamPlayer.fantasy_team_id) == team_id
                        )
                    ).all()
                )
                _add_players_in(
                    session, fteam, [pid for pid in player_ids if pid not in current]
                )
                _remove_players_in(session, team_id, current - set(player_ids))

        if created:
            # A captain earns the fantasy role, so the guild hears about the team
            discord_roles.sync([fantasy_team.captain_id])
        return self.get(team_id)

    def delete(self, fantasy_team_id: int) -> None:
        with Session.begin() as session:
            FantasyTeam.delete(session, fantasy_team_id)

    def get(self, fantasy_team_id: int) -> FantasyTeamPublic:
        """One team; its captain and drafted players carry their record in its
        season. Every team write answers through this read."""
        with Session.begin() as session:
            fteam = session.get(FantasyTeam, fantasy_team_id, options=_loads())
            if not fteam:
                raise NotFoundError("Fantasy Team not found")
            members = (fteam.captain_id, *(dp.user_id for dp in fteam.drafted_players))
            load_players(session, members, fteam.season_id)
            return _publics(session, [fteam])[0]

    def get_all(
        self, limit: int | None = None, offset: int = 0
    ) -> tuple[list[FantasyTeamPublic], int]:
        """The teams, or one page of them, and the total row count."""
        with Session.begin() as session:
            total = session.scalar(select(func.count()).select_from(FantasyTeam)) or 0
            # Offset paging is deterministic only with a fixed order
            statement = (
                select(FantasyTeam)
                .options(*_list_loads())
                .order_by(col(FantasyTeam.id))
                .offset(offset)
                .limit(limit)
            )
            fteams = session.scalars(statement).unique().all()
            return _publics(session, fteams), total

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
                .options(*_list_loads())
                .where(filter)
                .order_by(col(FantasyTeam.id))
                .offset(offset)
                .limit(limit)
            )
            fteams = session.scalars(statement).unique().all()
            return _publics(session, fteams), total

    def add_players(
        self, team_id: int, player_ids: list[int], *, member: bool = False
    ) -> FantasyTeamPublic:
        """Add the players to the team; a member's roster keeps to one player per tier."""
        with Session.begin() as session:
            fteam = session.get(FantasyTeam, team_id)
            if not fteam:
                raise NotFoundError(f"Fantasy Team not found by id: {team_id}")
            if member:
                # The roster the write would leave behind, checked before it runs
                current = session.scalars(
                    select(col(DBFantasyTeamPlayer.user_id)).where(
                        col(DBFantasyTeamPlayer.fantasy_team_id) == team_id
                    )
                ).all()
                _check_roster(
                    session,
                    fteam.season_id,
                    sorted({*current, *player_ids}),
                    complete=False,
                )
            _add_players_in(session, fteam, player_ids)
        return self.get(team_id)

    def remove_players(self, team_id: int, player_ids: list[int]) -> FantasyTeamPublic:
        with Session.begin() as session:
            if not session.get(FantasyTeam, team_id):
                raise NotFoundError(f"Fantasy Team not found by id: {team_id}")
            for user_id in player_ids:
                if not session.get(User, user_id):
                    raise NotFoundError(f"User not found by id: {user_id}")
            _remove_players_in(session, team_id, player_ids)
        return self.get(team_id)
