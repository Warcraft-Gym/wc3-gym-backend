"""The Discord roles the database says an account earns, and the sync to the guild.

The database is the source: an admin grant, a captain seat, a roster row, a
signup, a fantasy team or a champion binding earns the role a
discord_role_binding names. Sync grants what is missing and takes back only
bound roles the account no longer earns; a role no binding names is left alone.
Every write that changes an expectation calls sync after its transaction
commits.

With no DISCORD_BOT_TOKEN the guild answers nothing, so every function here is
a no-op that returns empty results.
"""

import logging
from collections.abc import Iterable, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core.db import Session
from app.core.exceptions import NotFoundError
from app.models.admin_grant import AdminGrant, env_ids
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
from app.services import discord

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


def expected_roles(user: User, session: OrmSession) -> set[str]:
    """The bound roles this account earns right now.

    admin is a grant or an environment id, captain a seat of the current
    season, team a roster row or a captain seat of that team,
    gnl_participant a roster row or a signup, fantasy a drafted team, and
    champion a roster row of the team and season the binding names.
    """
    season_id = _current_season(session)
    rosters = {
        (row.team_id, row.season_id)
        for row in session.scalars(
            select(DBUserTeamSeason).where(col(DBUserTeamSeason.user_id) == user.id)
        )
    }
    played = {team_id for team_id, season in rosters if season == season_id}
    captained = {
        row.team_id
        for row in session.scalars(
            select(DBTeamSeasonCaptain).where(
                col(DBTeamSeasonCaptain.user_id) == user.id,
                col(DBTeamSeasonCaptain.season_id) == season_id,
            )
        )
    }
    signed_up = bool(
        season_id is not None
        and session.get(
            DBUserSeasonSignup, {"user_id": user.id, "season_id": season_id}
        )
    )
    drafted = session.scalar(
        select(func.count())
        .select_from(FantasyTeam)
        .where(
            col(FantasyTeam.captain_id) == user.id,
            col(FantasyTeam.season_id) == season_id,
        )
    )

    roles: set[str] = set()
    for binding in session.scalars(select(DiscordRoleBinding)):
        if binding.kind is RoleKind.champion:
            # No column names a season winner, so a champion row names the team
            earned = (binding.team_id, binding.season_id) in rosters
        elif binding.season_id is not None and binding.season_id != season_id:
            earned = False
        elif binding.kind is RoleKind.admin:
            earned = user.discordId in env_ids() or bool(
                session.get(AdminGrant, user.discordId)
            )
        elif binding.kind is RoleKind.captain:
            earned = bool(captained)
        elif binding.kind is RoleKind.team:
            earned = binding.team_id in played | captained
        elif binding.kind is RoleKind.gnl_participant:
            earned = bool(played or signed_up)
        else:
            earned = bool(drafted)
        if earned:
            roles.add(binding.discord_role)
    return roles


def _accounts(session: OrmSession, user_ids: Iterable[int] | None) -> Sequence[User]:
    """The accounts to check: those with a Discord id, in id order."""
    statement = select(User).where(col(User.discordId) != "")
    if user_ids is not None:
        statement = statement.where(col(User.id).in_(list(user_ids)))
    return session.scalars(statement.order_by(col(User.id))).all()


def _diffs(session: OrmSession, users: Sequence[User]) -> list[DiscordRoleReport]:
    """The accounts whose guild roles differ from what the database says."""
    bound = {
        binding.discord_role for binding in session.scalars(select(DiscordRoleBinding))
    }
    reports = []
    for user in users:
        actual = discord.member_roles(user.discordId)
        if actual is None:
            continue
        expected = expected_roles(user, session)
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
    # ponytail: one guild read per account with a Discord id, one after the
    # other; an admin page on a 1 GiB box. Page it if the guild outgrows that.
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
        return [
            DiscordRoleBindingPublic.model_validate(binding)
            for binding in DiscordRoleBinding.get_all(session)
        ]


def add_binding(data: DiscordRoleBindingCreate) -> DiscordRoleBindingPublic:
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
        return DiscordRoleBindingPublic.model_validate(binding)


def delete_binding(binding_id: int) -> None:
    with Session.begin() as session:
        if not DiscordRoleBinding.delete(session, binding_id):
            raise NotFoundError(f"Discord role binding not found by id: {binding_id}")
