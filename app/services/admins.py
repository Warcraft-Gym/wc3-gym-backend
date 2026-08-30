"""Who administers the site, and the Discord role that mirrors it.

An admin is a row of admin_grant or an id in ADMIN_DISCORD_IDS. The
environment ids are the bootstrap: they need no row and no grant can take
them back. Every change syncs the account's bound roles.
"""

from sqlalchemy import select
from sqlmodel import col

from app.core.db import Session
from app.core.exceptions import BadRequestError, NotFoundError
from app.models.admin_grant import AdminGrant, AdminPublic, env_ids
from app.models.user import User
from app.services import discord_roles

BY_ENVIRONMENT = "Already an admin by environment"


def is_admin(discord_id: str) -> bool:
    """Whether that Discord account administers the site."""
    if discord_id in env_ids():
        return True
    with Session.begin() as session:
        return session.get(AdminGrant, discord_id) is not None


def admins() -> list[AdminPublic]:
    """The environment ids first, then the grants in the order they were made."""
    with Session.begin() as session:
        ids = sorted(env_ids())
        names = {
            user.discordId: user.name
            for user in session.scalars(
                select(User).where(col(User.discordId).in_(ids))
            )
        }
        rows = session.scalars(
            select(AdminGrant).order_by(col(AdminGrant.granted_at))
        ).all()
        return [
            AdminPublic(discord_id=one, name=names.get(one, ""), source="env")
            for one in ids
        ] + [AdminPublic(**row.model_dump(), source="app") for row in rows]


def grant(discord_id: str, granted_by: str, name: str = "") -> AdminPublic:
    """Make that account an admin. A second grant changes nothing."""
    if discord_id in env_ids():
        raise BadRequestError(BY_ENVIRONMENT)
    with Session.begin() as session:
        user = session.scalars(
            select(User).where(col(User.discordId) == discord_id)
        ).first()
        row = session.get(AdminGrant, discord_id)
        if not row:
            row = AdminGrant(
                discord_id=discord_id,
                name=name or (user.name if user else ""),
                granted_by=granted_by,
            )
            session.add(row)
            session.flush()
        public = AdminPublic(**row.model_dump(), source="app")
        user_id = user.id if user else None
    _mirror(user_id)
    return public


def revoke(discord_id: str, by: str) -> None:
    """Take a grant back. The environment ids and the caller's own grant stay."""
    if discord_id in env_ids():
        raise BadRequestError(BY_ENVIRONMENT)
    if discord_id == by:
        raise BadRequestError("Admins cannot revoke themselves")
    with Session.begin() as session:
        row = session.get(AdminGrant, discord_id)
        if not row:
            raise NotFoundError(f"Admin not found by Discord id: {discord_id}")
        session.delete(row)
        user = session.scalars(
            select(User).where(col(User.discordId) == discord_id)
        ).first()
        user_id = user.id if user else None
    _mirror(user_id)


def _mirror(user_id: int | None) -> None:
    """Push the account's bound roles to the guild, once the grant is committed."""
    # ponytail: an admin with no users row gets no Discord role; link the account to mirror it
    if user_id:
        discord_roles.sync([user_id])
