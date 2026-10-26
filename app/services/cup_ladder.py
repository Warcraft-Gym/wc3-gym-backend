"""The ladder games of a cup's players, read once a sign-up has answered.

The match sync reads a player's games for a GNL window, so a player who only
plays cups would have none stored. A cup sign-up therefore names its player
here, and after the answer is out the app reads that player's games of the
current w3champions season. The nightly member sync then keeps them fresh
while the cup is to come (`users.stalest_members`).

The sign-up routes take `after_signups`, which collects the players of one
request; `want` adds to it from the one place every sign-up passes,
`events._refresh_for`.
"""

import logging
from contextvars import ContextVar
from datetime import timedelta

from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlmodel import col

from app.core.db import Session
from app.core.exceptions import ExternalServiceError
from app.models.user import User, UserReduced

log = logging.getLogger(__name__)

# A player read for the season this recently is read again by the nightly sync, not here
FRESH = timedelta(hours=1)

_wanted: ContextVar[list[int] | None] = ContextVar("cup_ladder_wanted", default=None)


async def after_signups(background: BackgroundTasks) -> None:
    """A route dependency: the cup players this request signs up have their
    ladder games read once the answer is out.

    It runs in the request's own context, before the route, so the list it
    sets reaches the route's thread and the background task reads it after.
    """
    wanted: list[int] = []
    _wanted.set(wanted)
    background.add_task(read_games, wanted)


def want(user_id: int) -> None:
    """Name a cup sign-up's player for the read after the answer. Outside a
    route that took `after_signups` nothing is named."""
    wanted = _wanted.get()
    if wanted is not None:
        wanted.append(user_id)


def read_games(user_ids: list[int]) -> None:
    """Read these players' games of the current w3champions season. A failure
    is logged and never reaches the sign-up, which has answered already."""
    if not user_ids:
        return
    try:
        sync(list(dict.fromkeys(user_ids)))
    except ExternalServiceError as error:
        log.info(f"No ladder games read after a cup sign-up: {error}")


def sync(user_ids: list[int]) -> None:
    """The players with a battle tag, synced over the current season."""
    from app.services.ladder import LadderService
    from app.services.settings import SettingsService

    with Session() as session:
        users = [
            UserReduced(id=row.id, name=row.name, battleTag=row.battleTag)
            for row in session.execute(
                select(col(User.id), col(User.name), col(User.battleTag)).where(
                    col(User.id).in_(user_ids), col(User.battleTag).is_not(None)
                )
            )
        ]
    if users:
        LadderService(settings_app_service=SettingsService()).sync_current_season(
            users, FRESH
        )
