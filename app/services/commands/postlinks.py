"""/postlinks: the site's links as buttons, posted by an admin.

The site signs a member in through Clerk with Discord OAuth, so the buttons
are plain links and carry no token.
"""

import os
from typing import Any

from app.models.season import SeasonPhase
from app.services import admins, discord, discord_roles, series_cards
from app.services.commands.base import (
    PRIVATE,
    PUBLIC,
    Services,
    caller,
    md,
    options_of,
)

COMMAND: dict[str, Any] = {
    "name": "postlinks",
    "description": "Post the Warcraft Gym links as buttons",
    "options": [
        {
            "type": 7,
            "name": "channel",
            "description": "Post there instead of this channel",
        }
    ],
}

SIGN_IN = "Sign in with your Discord account to use these."
CLOSED = "Signups are closed. A signup is subject to admin approval."
SIGNUPS: dict[SeasonPhase | None, str] = {
    "open": "Signups are open.",
    "complete": "Signups are closed.",
}


def _content(services: Services) -> str:
    """The current season, its Round 1 dates and whether signups are open."""
    season_id = discord_roles.current_season()
    if season_id is None:
        return f"**Warcraft Gym**\n{SIGN_IN}"
    season = services.seasons.get(season_id)
    return "\n".join(
        [
            f"**{md(season.name or '?')}**",
            series_cards.round_line(season_id, 1),
            f"{SIGNUPS.get(season.phase, CLOSED)} {SIGN_IN}",
        ]
    )


# label, path
LINKS = [
    ("Sign up", "/signup"),
    ("Player dashboard", "/player-dashboard"),
    ("Fantasy", "/fantasy-registration"),
]


def run(payload: dict[str, Any], services: Services) -> tuple[dict[str, Any], bool]:
    """/postlinks channel: one message with the three link buttons."""
    discord_id, _ = caller(payload)
    if not admins.is_admin(discord_id):
        return {"content": "Admins only."}, PRIVATE
    site = (os.getenv("FRONTEND_URL") or "").rstrip("/")
    if not site:
        return {"content": "FRONTEND_URL is not set."}, PRIVATE
    message = {
        "content": _content(services),
        "components": [
            {
                "type": 1,
                "components": [
                    {"type": 2, "style": 5, "label": label, "url": site + path}
                    for label, path in LINKS
                ],
            }
        ],
    }
    channel_id = options_of(payload).get("channel")
    if not channel_id:
        return message, PUBLIC
    if not discord.post_to_channel(str(channel_id), message):
        return {"content": "Discord refused the post."}, PRIVATE
    return {"content": f"Posted in <#{channel_id}>."}, PRIVATE
