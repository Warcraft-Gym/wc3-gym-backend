"""/postlinks: the site's links as buttons, posted by an admin.

The site signs a member in through Clerk with Discord OAuth, so the buttons
are plain links and carry no token.
"""

import os
from typing import Any

from app.services import admins, discord
from app.services.commands.base import PRIVATE, PUBLIC, Services, caller, options_of

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

CONTENT = "**Warcraft Gym**\nSign in with your Discord account to use these."

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
        "content": CONTENT,
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
