"""The local dev login: sign in as any player, to test the app as that player.

A local instance has no Discord server, so no Clerk session passes the guild
check. With DEV_LOGIN=1 on a local backend these routes mint a session for
any player that has a Discord id, as a member, a guest or an admin; a member
with a seat is a captain, as on a real login. Every route answers 404 unless
`dev_login_enabled` holds.
"""

import os
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import ColumnElement, func, or_, select
from sqlmodel import col

from app.api.deps import TeamServiceDep
from app.core.db import Session
from app.core.exceptions import ApiError
from app.core.security import create_access_token, dev_login_enabled
from app.models.base import ident
from app.models.user import User

router = APIRouter(prefix="/dev", tags=["dev"], include_in_schema=False)

LIMIT = 30


class DevPlayer(BaseModel):
    id: int
    name: str
    battle_tag: str | None
    captain: bool


class DevLoginRequest(BaseModel):
    user_id: int
    role: Literal["member", "guest", "admin"] = "member"


def _enabled() -> None:
    if not dev_login_enabled():
        raise ApiError(404, {"error": "Not Found"})


def _with_login() -> tuple[ColumnElement[bool], ...]:
    """Only a row with a real Discord id can hold a session: not null, not blank, not a `gnl-` stand-in."""
    discord_id = func.trim(col(User.discordId))
    return (
        col(User.discordId).is_not(None),
        discord_id != "",
        ~discord_id.like("gnl-%"),
    )


@router.get("/players")
def dev_players(teams: TeamServiceDep, search: str = "") -> list[DevPlayer]:
    """Up to 30 players that can sign in, by name or battle tag, each marked when it captains."""
    _enabled()
    query = select(User).where(*_with_login()).order_by(col(User.name)).limit(LIMIT)
    if search.strip():
        like = f"%{search.strip().lower()}%"
        query = query.where(
            or_(
                func.lower(col(User.name)).like(like),
                func.lower(User.battleTag).like(like),
            )
        )
    with Session.begin() as session:
        rows = [
            (ident(user), user.name, user.battleTag, user.discordId)
            for user in session.scalars(query)
        ]
    return [
        DevPlayer(
            id=user_id,
            name=name,
            battle_tag=battle_tag,
            captain=bool(teams.captain_seats(str(discord_id))),
        )
        for user_id, name, battle_tag, discord_id in rows
    ]


@router.post("/login")
def dev_login(data: DevLoginRequest) -> dict[str, str]:
    """A session for one player, as the role asked for."""
    _enabled()
    with Session.begin() as session:
        user = session.scalars(
            select(User).where(col(User.id) == data.user_id, *_with_login())
        ).first()
        if user is None:
            raise ApiError(
                400, {"error": "That player has no Discord id, so it cannot sign in"}
            )
        discord_id, name = str(user.discordId).strip(), user.name
    token = create_access_token(
        discord_id,
        int(os.getenv("TOKEN_TIME", "60")),
        kind="dev",
        extra={"role": data.role, "name": name},
    )
    return {"access_token": token}
