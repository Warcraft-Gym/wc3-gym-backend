"""Ask W3Champions for one player's rating at the moment it decides something.

An event that refuses a signup outside its MMR range reads the rating of the
day, not the one the last sync stored. A player the app asked about in the
last hour is not asked again, so a repeated signup sends no traffic, and a
refused ask leaves the stored rating to decide.
"""

import logging

from app.core.db import Session
from app.core.exceptions import ExternalServiceError
from app.models.types import utcnow
from app.models.user import User, UserReduced

logger = logging.getLogger(__name__)

# A signup waits on this call, so it gives up after five seconds
REFRESH_TIMEOUT = 5.0
# How many seconds a player the app already asked about waits for the next ask
REFRESH_AGAIN = 3600


def refresh_rating(user_id: int, battle_tag: str) -> None:
    """Read the player's W3Champions stats again, at most once an hour."""
    from app.services.settings import SettingsService
    from app.services.users import UserService

    with Session.begin() as session:
        user = session.get(User, user_id)
        asked = user.w3c_synced_at if user is not None else None
        if asked is not None and (utcnow() - asked).total_seconds() < REFRESH_AGAIN:
            return
    try:
        UserService(settings_app_service=SettingsService()).update_w3c_stats(
            UserReduced(id=user_id, battleTag=battle_tag), timeout=REFRESH_TIMEOUT
        )
    except ExternalServiceError as error:
        logger.info(f"No fresh W3Champions rating for a signup: {error}")
