"""Register the guild's slash commands and upload the app emojis.

The production build runs this after the migrations (`vercel.json`), with the
production environment, so the bot token stays in Vercel and no one runs the
step by hand. Both writes repeat safely: the command list replaces itself, and
an emoji that exists already is left alone. A Discord that refuses or cannot be
reached prints a warning and the build goes on, since a release never waits on
Discord. Without the three Discord values it does nothing.
"""

import os
import sys
from pathlib import Path

from app.core.exceptions import ApiError
from app.services import discord
from app.services.interactions import register_commands

EMOJIS = Path("docs/discord-emojis")
NEEDED = ("DISCORD_APPLICATION_ID", "DISCORD_GUILD_ID", "DISCORD_BOT_TOKEN")


def _reason(error: Exception) -> str:
    """What went wrong, in one line, without the request or its token."""
    if isinstance(error, ApiError):
        return f"{error.status_code} {error}"
    return type(error).__name__


def main() -> int:
    missing = [name for name in NEEDED if not os.getenv(name)]
    if missing:
        print(f"Discord setup skipped: {', '.join(missing)} not set")
        return 0
    try:
        print(f"Discord commands registered: {', '.join(register_commands())}")
    except Exception as error:  # a release never waits on Discord
        print(f"Warning: the Discord commands were not registered: {_reason(error)}")
    try:
        added = discord.upload_app_emojis(EMOJIS)
        print(f"Discord emojis uploaded: {', '.join(added) or 'none new'}")
    except Exception as error:  # a release never waits on Discord
        print(f"Warning: the Discord emojis were not uploaded: {_reason(error)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
