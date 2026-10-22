---
type: Runbook
title: Set up the Discord side
description: Create the application, let the production build register the slash commands and upload the emojis, place the bot role, and point the channel settings rows at the right channels.
resource: ../../../justfile
tags: [discord]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-22T10:00:00Z }
stale_after: 2027-03-14T00:00:00Z
sources:
  - id: justfile
    resource: ../../../justfile
    title: discord-commands and discord-emojis
  - id: discord-setup
    resource: ../../../api/discord_setup.py
    title: The production build's Discord step
  - id: emojis
    resource: ../../discord-emojis
    title: The race icons and the W3Champions crown
---

# Steps

1. In the Discord Developer Portal, create the application with a bot. Set `DISCORD_APPLICATION_ID`, `DISCORD_PUBLIC_KEY`, `DISCORD_BOT_TOKEN` and `DISCORD_GUILD_ID` on the backend. The interactions endpoint URL is the adapter's, not the backend's; see the `wc3-gym-discord-bot` repository.
2. Each production build registers the commands on the guild `DISCORD_GUILD_ID` names, after the migrations: `api/discord_setup.py`, run by the `buildCommand` in `vercel.json`. It replaces the guild's command list with `COMMANDS` from `app/services/interactions.py`, and guild commands update at once. A new guild or a new application needs its values set on the production deployment and a release. On staging or locally, `uv run just discord-commands` registers them by hand.
3. The same step uploads the emojis in `docs/discord-emojis` that the application lacks, and leaves an emoji it holds as it is. `/stats` and the cards show race icons and the W3Champions crown once they exist. By hand: `uv run just discord-emojis`.
4. In the guild, place the bot's role directly above the season and team roles and below everything else, with Manage Roles. A bot manages only roles below its own; a role higher up is out of its reach on purpose.
5. Set the `settings` rows `results_channel_id` and `content_channel_id` to the channels the cards go to. Before a write test against staging, point them at a test channel; a staging row may name a live channel.
6. For cup announcements, set `announcement_channel_id` to the channel and `announcement_role_id` to the role members take on Home. Place the role below the bot's role, and bind it to no role kind, so the role sync leaves it alone.
7. Add the Discord role bindings under Config > Discord roles. New bindings start ignored; mark one synced to let the button manage it.

# Facts

- The production build's Discord step never fails the build. A missing `DISCORD_*` value skips it, and a Discord that refuses or cannot be reached prints a warning in the build log. After a release that changes the guild or the application, the build log reads `Discord commands registered` with the command names.
- The guild the backend reads is a maintainers' decision. Changing it needs new role ids in the bindings.
- The bot's token can read a channel over REST; it cannot write forum tags without Manage Threads.
- Test posts to a test channel use `allowed_mentions: {"parse": []}` so nobody is pinged.
