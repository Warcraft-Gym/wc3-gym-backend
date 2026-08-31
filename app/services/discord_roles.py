"""The Discord roles the database says an account earns, and the sync to the guild.

The database is the source: a captain seat, a roster row, a signup, a fantasy
team or a season's standings earns the role a discord_role_binding names. Sync
grants what is missing and takes back only bound roles the account no longer
earns; a role no binding names is left alone, and so is every admin binding —
those roles are hand-managed in the guild. Every write that changes an
expectation calls sync after its transaction commits.

With no DISCORD_BOT_TOKEN the guild answers nothing, so every function here is
a no-op that returns empty results.
"""

import logging
from collections import defaultdict
from collections.abc import Iterable, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core.db import Session
from app.core.exceptions import BadRequestError, NotFoundError
from app.models.base import ident
from app.models.discord_role_binding import (
    DiscordRoleBinding,
    DiscordRoleBindingCreate,
    DiscordRoleBindingPublic,
    DiscordRoleBindingUpdate,
    DiscordRoleReport,
)
from app.models.enums import RoleKind
from app.models.fantasy_team import FantasyTeam
from app.models.relationships import DBTeamSeasonCaptain, DBUserSeasonSignup
from app.models.season import Season
from app.models.settings import Settings
from app.models.user import User
from app.models.user_team_season import DBUserTeamSeason
from app.services import derived, discord

logger = logging.getLogger(__name__)


def _current_season(session: OrmSession) -> int | None:
    """The season the roles follow, as the admin pages resolve it."""
    setting = Settings.get_by_key(session, "current_gnl_season")
    value = setting.value if setting else None
    if value and value.isdigit():
        return int(value)
    return session.scalar(select(func.max(col(Season.id))))


def current_season() -> int | None:
    """The season the roles follow, read in a session of its own."""
    with Session.begin() as session:
        return _current_season(session)


def _synced_bindings(session: OrmSession) -> Sequence[DiscordRoleBinding]:
    """The bindings the sync acts on: every kind but the hand-managed admin."""
    return session.scalars(
        select(DiscordRoleBinding).where(col(DiscordRoleBinding.kind) != RoleKind.admin)
    ).all()


def _season_winners(session: OrmSession, season_ids: set[int]) -> dict[int, int]:
    """The team that tops each of those seasons' derived standings.

    Ties break by fewer points against, then the older team, matching what
    the standings read as first place.
    """
    if not season_ids:
        return {}
    rules = derived._rules_by_season(session, season_ids)
    sums = derived._sums_by_team(session, rules)
    best: dict[int, tuple[int, int, int]] = {}
    for (team_id, season_id), (final, against) in sums.items():
        key = (-final, against, team_id)
        if season_id not in best or key < best[season_id]:
            best[season_id] = key
    return {season_id: team_id for season_id, (_, _, team_id) in best.items()}


def expected_roles_of(
    users: Sequence[User], session: OrmSession
) -> dict[int, set[str]]:
    """The bound roles each of those accounts earns right now, in a handful of queries.

    captain is a seat of the current season and team a roster row or a
    captain seat of that team, both only while the binding's season (if any)
    is current. gnl_participant is a roster row or a signup and fantasy a
    drafted team, each of the binding's season — or of the current one when
    the binding names none — kept after that season ends. champion is a
    roster row of the team that tops the named season's standings.
    """
    season_id = _current_season(session)
    ids = [ident(user) for user in users]
    rosters: dict[int, set[tuple[int, int]]] = defaultdict(set)
    for row in session.scalars(
        select(DBUserTeamSeason).where(col(DBUserTeamSeason.user_id).in_(ids))
    ):
        rosters[row.user_id].add((row.team_id, row.season_id))
    captained: dict[int, set[int]] = defaultdict(set)
    for row in session.scalars(
        select(DBTeamSeasonCaptain).where(
            col(DBTeamSeasonCaptain.user_id).in_(ids),
            col(DBTeamSeasonCaptain.season_id) == season_id,
        )
    ):
        captained[row.user_id].add(row.team_id)
    signups = {
        (user_id, signup_season)
        for user_id, signup_season in session.execute(
            select(
                col(DBUserSeasonSignup.user_id), col(DBUserSeasonSignup.season_id)
            ).where(col(DBUserSeasonSignup.user_id).in_(ids))
        )
    }
    drafted = {
        (captain_id, drafted_season)
        for captain_id, drafted_season in session.execute(
            select(col(FantasyTeam.captain_id), col(FantasyTeam.season_id)).where(
                col(FantasyTeam.captain_id).in_(ids)
            )
        )
    }
    bindings = _synced_bindings(session)
    winners = _season_winners(
        session,
        {
            binding.season_id
            for binding in bindings
            if binding.kind is RoleKind.champion and binding.season_id is not None
        },
    )

    roles: dict[int, set[str]] = {}
    for user in users:
        uid = ident(user)
        played = {team for team, season in rosters[uid] if season == season_id}
        seasons_played = {season for _, season in rosters[uid]}
        earned_roles: set[str] = set()
        for binding in bindings:
            if binding.kind is RoleKind.champion:
                earned = (winners.get(binding.season_id), binding.season_id) in rosters[
                    uid
                ]
            elif binding.kind is RoleKind.gnl_participant:
                season = binding.season_id or season_id
                earned = season in seasons_played or (uid, season) in signups
            elif binding.kind is RoleKind.fantasy:
                earned = (uid, binding.season_id or season_id) in drafted
            elif binding.season_id is not None and binding.season_id != season_id:
                earned = False
            elif binding.kind is RoleKind.captain:
                earned = bool(captained[uid])
            else:
                earned = binding.team_id in played | captained[uid]
            if earned:
                earned_roles.add(binding.discord_role)
        roles[uid] = earned_roles
    return roles


def _accounts(session: OrmSession, user_ids: Iterable[int] | None) -> Sequence[User]:
    """The accounts to check: those with a Discord id, in id order."""
    statement = select(User).where(col(User.discordId) != "")
    if user_ids is not None:
        statement = statement.where(col(User.id).in_(list(user_ids)))
    return session.scalars(statement.order_by(col(User.id))).all()


def _diffs(session: OrmSession, users: Sequence[User]) -> list[DiscordRoleReport]:
    """The accounts whose guild roles differ from what the database says."""
    bound = {binding.discord_role for binding in _synced_bindings(session)}
    expected_of = expected_roles_of(users, session)
    # A full report reads the guild once; a named few read their own members
    guild = discord.guild_members() if len(users) > 5 else None
    reports = []
    for user in users:
        if guild is not None:
            actual = guild.get(user.discordId)
        else:
            actual = discord.member_roles(user.discordId)
        if actual is None:
            continue
        expected = expected_of[ident(user)]
        missing = sorted(expected - actual)
        extra = sorted(bound & (actual - expected))
        if missing or extra:
            reports.append(
                DiscordRoleReport(
                    user_id=ident(user),
                    discord_id=user.discordId,
                    name=user.name,
                    missing=missing,
                    extra=extra,
                )
            )
    return reports


def report(user_ids: Iterable[int] | None = None) -> list[DiscordRoleReport]:
    """Every account the guild disagrees with, or those the caller names."""
    with Session.begin() as session:
        return _diffs(session, _accounts(session, user_ids))


def sync(user_ids: Iterable[int] | None = None) -> list[DiscordRoleReport]:
    """Grant what those accounts earn and take back the bound roles they do not."""
    with Session.begin() as session:
        reports = _diffs(session, _accounts(session, user_ids))
    for account in reports:
        for role in account.missing:
            discord.set_role([account.discord_id], role, grant=True)
        for role in account.extra:
            discord.set_role([account.discord_id], role, grant=False)
    return reports


def team_roles() -> dict[int, str]:
    """The role bound to each team, for the season export sheet."""
    with Session.begin() as session:
        return {
            binding.team_id: binding.discord_role
            for binding in session.scalars(
                select(DiscordRoleBinding).where(
                    col(DiscordRoleBinding.kind) == RoleKind.team
                )
            )
            if binding.team_id
        }


def bindings() -> list[DiscordRoleBindingPublic]:
    with Session.begin() as session:
        rows = DiscordRoleBinding.get_all(session)
        winners = _season_winners(
            session,
            {
                row.season_id
                for row in rows
                if row.kind is RoleKind.champion and row.season_id is not None
            },
        )
        answer = []
        for row in rows:
            public = DiscordRoleBindingPublic.model_validate(row)
            if row.kind is RoleKind.champion:
                # Derived, not stored: the page names the winning team with it
                public.team_id = winners.get(row.season_id)
            answer.append(public)
        return answer


def _check(kind: RoleKind, season_id: int | None, team_id: int | None) -> None:
    """Refuse a binding no account could ever earn."""
    if kind is RoleKind.admin:
        raise BadRequestError("Admin roles are hand-managed in Discord, not synced")
    if kind is RoleKind.team and team_id is None:
        raise BadRequestError("A team binding needs the team that earns it")
    if kind is RoleKind.champion and season_id is None:
        raise BadRequestError("A champion binding needs the season it crowns")
    if kind is RoleKind.champion and team_id is not None:
        raise BadRequestError("The champion team is derived from the standings")


def add_binding(data: DiscordRoleBindingCreate) -> DiscordRoleBindingPublic:
    _check(data.kind, data.season_id, data.team_id)
    with Session.begin() as session:
        binding = DiscordRoleBinding.add(session, data.model_dump())
        return DiscordRoleBindingPublic.model_validate(binding)


def update_binding(
    binding_id: int, data: DiscordRoleBindingUpdate
) -> DiscordRoleBindingPublic:
    with Session.begin() as session:
        binding = DiscordRoleBinding.update(
            session, binding_id, **data.model_dump(exclude_unset=True)
        )
        if not binding:
            raise NotFoundError(f"Discord role binding not found by id: {binding_id}")
        _check(binding.kind, binding.season_id, binding.team_id)
        return DiscordRoleBindingPublic.model_validate(binding)


def delete_binding(binding_id: int) -> None:
    with Session.begin() as session:
        if not DiscordRoleBinding.delete(session, binding_id):
            raise NotFoundError(f"Discord role binding not found by id: {binding_id}")
