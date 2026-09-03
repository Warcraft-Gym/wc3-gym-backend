"""The Discord roles the database says an account earns, and the sync to the guild.

The database is the source: a captain seat, a roster row, a signup, a fantasy
team or a season's standings earns the role a discord_role_binding names. Sync
grants what is missing and takes back only bound roles the account no longer
earns; a role no binding names is left alone, and so is a binding no admin
marked synced and every admin binding — those roles are hand-managed in the
guild. Every write that changes an expectation calls sync after its
transaction commits.

With no DISCORD_BOT_TOKEN the guild answers nothing, so every function here is
a no-op that returns empty results.
"""

import logging
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core.db import Session
from app.core.exceptions import BadRequestError, NotFoundError
from app.models.base import ident
from app.models.discord_role_binding import (
    DiscordRoleBinding,
    DiscordRoleBindingBase,
    DiscordRoleBindingCreate,
    DiscordRoleBindingPublic,
    DiscordRoleBindingUpdate,
    DiscordRoleHidden,
    DiscordRoleHiddenWrite,
    DiscordRoleReport,
    GuildRole,
    RoleGroup,
)
from app.models.enums import RoleKind, RoleScope
from app.models.fantasy_team import FantasyTeam
from app.models.relationships import DBTeamSeasonCaptain, DBUserSeasonSignup
from app.models.season import Season
from app.models.settings import Settings
from app.models.team import Team
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
    """The bindings the sync acts on: those marked synced, never the admin kind."""
    return session.scalars(
        select(DiscordRoleBinding).where(
            col(DiscordRoleBinding.synced).is_(True),
            col(DiscordRoleBinding.kind) != RoleKind.admin,
        )
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


def _earned_in(seasons: set[int], season: int | None) -> bool:
    """Whether one of those records falls in the season, or in any when the scope is all."""
    return bool(seasons) if season is None else season in seasons


def expected_roles_of(
    users: Sequence[User],
    session: OrmSession,
    bindings: Sequence[DiscordRoleBinding] | None = None,
) -> dict[int, set[str]]:
    """The bound roles each of those accounts earns right now, in a handful of queries.

    The binding's scope names the seasons that count: the current one, the
    season the binding names, or every season. captain is a captain seat,
    team a roster row or a captain seat of that team, gnl_participant a
    roster row or a signup and fantasy a drafted team, each in those seasons.
    champion is scoped to one season, and a roster row of the team that tops
    its standings earns it.
    """
    current = _current_season(session)
    ids = [ident(user) for user in users]
    rosters: dict[int, set[tuple[int, int]]] = defaultdict(set)
    for row in session.scalars(
        select(DBUserTeamSeason).where(col(DBUserTeamSeason.user_id).in_(ids))
    ):
        rosters[row.user_id].add((row.team_id, row.season_id))
    captained: dict[int, set[tuple[int, int]]] = defaultdict(set)
    for row in session.scalars(
        select(DBTeamSeasonCaptain).where(col(DBTeamSeasonCaptain.user_id).in_(ids))
    ):
        captained[row.user_id].add((row.team_id, row.season_id))
    signups: dict[int, set[int]] = defaultdict(set)
    for user_id, signup_season in session.execute(
        select(
            col(DBUserSeasonSignup.user_id), col(DBUserSeasonSignup.season_id)
        ).where(col(DBUserSeasonSignup.user_id).in_(ids))
    ):
        signups[user_id].add(signup_season)
    drafted: dict[int, set[int]] = defaultdict(set)
    for captain_id, drafted_season in session.execute(
        select(col(FantasyTeam.captain_id), col(FantasyTeam.season_id)).where(
            col(FantasyTeam.captain_id).in_(ids)
        )
    ):
        drafted[captain_id].add(drafted_season)
    if bindings is None:
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
        seats = captained[uid]
        earned_roles: set[str] = set()
        for binding in bindings:
            if binding.kind is RoleKind.champion:
                earned = (winners.get(binding.season_id), binding.season_id) in rosters[
                    uid
                ]
                if earned:
                    earned_roles.add(binding.discord_role)
                continue
            # None is every season, which is what the all scope reads
            if binding.scope is RoleScope.all:
                season = None
            elif binding.scope is RoleScope.season:
                season = binding.season_id
            else:
                season = current
            if binding.kind is RoleKind.captain:
                earned = _earned_in({one for _, one in seats}, season)
            elif binding.kind is RoleKind.team:
                earned = _earned_in(
                    {
                        one
                        for team, one in rosters[uid] | seats
                        if team == binding.team_id
                    },
                    season,
                )
            elif binding.kind is RoleKind.gnl_participant:
                earned = _earned_in(
                    {one for _, one in rosters[uid]} | signups[uid], season
                )
            else:
                earned = _earned_in(drafted[uid], season)
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


def _diffs(
    session: OrmSession, users: Sequence[User], roles: set[str] | None = None
) -> list[DiscordRoleReport]:
    """The accounts whose guild roles differ from what the database says.

    With roles named, only those bound roles are compared and the rest are
    left as the guild holds them.
    """
    bound = {binding.discord_role for binding in _synced_bindings(session)}
    if roles is not None:
        bound &= roles
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
        expected = expected_of[ident(user)] & bound
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


def sync(
    user_ids: Iterable[int] | None = None, role_ids: Iterable[str] | None = None
) -> list[DiscordRoleReport]:
    """Grant what those accounts earn and take back the bound roles they do not."""
    with Session.begin() as session:
        reports = _diffs(
            session,
            _accounts(session, user_ids),
            set(role_ids) if role_ids is not None else None,
        )
    for account in reports:
        for role in account.missing:
            discord.set_role(account.discord_id, role, grant=True)
        for role in account.extra:
            discord.set_role(account.discord_id, role, grant=False)
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


def guild_roles() -> list[GuildRole]:
    """Every guild role, with the ones an admin hid flagged as hidden."""
    roles = discord.guild_roles()
    with Session.begin() as session:
        hidden = set(session.scalars(select(col(DiscordRoleHidden.discord_role))))
    for role in roles:
        role.hidden = role.id in hidden
    return roles


def hide_role(discord_role: str) -> DiscordRoleHiddenWrite:
    """Hide a role the app must never touch. Hiding a hidden role changes nothing."""
    with Session.begin() as session:
        bound = session.scalar(
            select(DiscordRoleBinding).where(
                col(DiscordRoleBinding.discord_role) == discord_role
            )
        )
        if bound is not None:
            raise BadRequestError("Unbind the role before hiding it")
        row = session.get(DiscordRoleHidden, discord_role)
        if row is None:
            row = DiscordRoleHidden.add(session, {"discord_role": discord_role})
        return DiscordRoleHiddenWrite.model_validate(row)


def unhide_role(discord_role: str) -> None:
    """Show the role again, so a binding can name it."""
    with Session.begin() as session:
        row = session.get(DiscordRoleHidden, discord_role)
        if row is None:
            raise NotFoundError(f"Discord role is not hidden: {discord_role}")
        session.delete(row)


def _group_key(group: RoleGroup) -> str:
    """The synthetic role id a group is counted under."""
    return f"{group.kind.value}:{group.team_id or ''}"


def _season_teams(session: OrmSession, season_id: int | None) -> Sequence[Team]:
    """The teams that played or were captained in that season, or in any of them, by name."""
    rosters = select(col(DBUserTeamSeason.team_id))
    seats = select(col(DBTeamSeasonCaptain.team_id))
    if season_id is not None:
        rosters = rosters.where(col(DBUserTeamSeason.season_id) == season_id)
        seats = seats.where(col(DBTeamSeasonCaptain.season_id) == season_id)
    team_ids = set(session.scalars(rosters)) | set(session.scalars(seats))
    return session.scalars(
        select(Team).where(col(Team.id).in_(team_ids)).order_by(col(Team.name))
    ).all()


def role_groups(
    season_id: int | None = None, scope: RoleScope = RoleScope.current
) -> list[RoleGroup]:
    """Every group of accounts a binding of that scope can name, and how many earn it now."""
    with Session.begin() as session:
        season = season_id or _current_season(session)
        # A group carries the season only when its scope reads one
        named = season if scope is RoleScope.season else None
        groups = [
            RoleGroup(
                kind=RoleKind.captain, scope=scope, season_id=named, label="Captains"
            ),
            RoleGroup(
                kind=RoleKind.gnl_participant,
                scope=scope,
                season_id=named,
                label="Players",
            ),
            RoleGroup(
                kind=RoleKind.fantasy, scope=scope, season_id=named, label="Bettors"
            ),
            RoleGroup(
                kind=RoleKind.champion,
                scope=RoleScope.season,
                season_id=season,
                label="Champions",
            ),
        ]
        for team in _season_teams(session, None if scope is RoleScope.all else season):
            groups.append(
                RoleGroup(
                    kind=RoleKind.team,
                    scope=scope,
                    season_id=named,
                    team_id=ident(team),
                    label=team.name,
                )
            )
        bindings = [
            DiscordRoleBinding(
                kind=group.kind,
                scope=group.scope,
                season_id=group.season_id,
                team_id=group.team_id,
                discord_role=_group_key(group),
            )
            for group in groups
        ]
        earned = expected_roles_of(_accounts(session, None), session, bindings)
        counts = Counter(role for roles in earned.values() for role in roles)
        for group in groups:
            group.count = counts[_group_key(group)]
        return groups


def _manageable(discord_role: str) -> None:
    """Refuse a role the bot sits below; a role the guild does not name is allowed."""
    role = next((one for one in discord.guild_roles() if one.id == discord_role), None)
    if role is not None and not role.manageable:
        raise BadRequestError(
            "The bot cannot manage that role: it sits above the bot in Discord"
        )


def _unhidden(session: OrmSession, discord_role: str) -> None:
    """Refuse a role an admin hid: the app must never touch it."""
    if session.get(DiscordRoleHidden, discord_role) is not None:
        raise BadRequestError("Unhide the role before binding it")


def _check(binding: DiscordRoleBindingBase) -> None:
    """Refuse a binding no account could ever earn, and drop a season its scope never reads."""
    if binding.kind is RoleKind.admin:
        raise BadRequestError("Admin roles are hand-managed in Discord, not synced")
    if binding.kind is RoleKind.team and binding.team_id is None:
        raise BadRequestError("A team binding needs the team that earns it")
    if binding.kind is RoleKind.champion:
        if binding.scope is not RoleScope.season:
            raise BadRequestError(
                "A champion binding crowns one season, so its scope is season"
            )
        if binding.team_id is not None:
            raise BadRequestError("The champion team is derived from the standings")
    if binding.scope is RoleScope.season:
        if binding.season_id is None:
            raise BadRequestError("A season binding needs the season it follows")
    else:
        binding.season_id = None


def add_binding(data: DiscordRoleBindingCreate) -> DiscordRoleBindingPublic:
    _check(data)
    _manageable(data.discord_role)
    with Session.begin() as session:
        _unhidden(session, data.discord_role)
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
        _check(binding)
        _unhidden(session, binding.discord_role)
        _manageable(binding.discord_role)
        return DiscordRoleBindingPublic.model_validate(binding)


def delete_binding(binding_id: int) -> None:
    with Session.begin() as session:
        if not DiscordRoleBinding.delete(session, binding_id):
            raise NotFoundError(f"Discord role binding not found by id: {binding_id}")
