---
type: Runbook
title: Set up the Discord side
description: Register the slash commands, upload the emojis, place the bot role, and point the channel settings rows at the right channels.
tags: [runbook, discord]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: justfile
    resource: ../../../justfile
    title: discord-commands and discord-emojis
  - id: emojis
    resource: ../../discord-emojis
    title: The race icons and the W3Champions crown
---

# Steps

1. In the Discord Developer Portal, create the application with a bot. Set `DISCORD_APPLICATION_ID`, `DISCORD_PUBLIC_KEY`, `DISCORD_BOT_TOKEN` and `DISCORD_GUILD_ID` on the backend. The interactions endpoint URL is the adapter's, not the backend's; see the `wc3-gym-discord-bot` repository.
2. Register the commands on the guild: `uv run just discord-commands`. It replaces the guild's command list with `COMMANDS` from `app/services/interactions.py`. Guild commands update at once.
3. Upload the app emojis: `uv run just discord-emojis`. `/stats` and the cards show race icons and the W3Champions crown once they exist.
4. In the guild, place the bot's role directly above the season and team roles and below everything else, with Manage Roles. A bot manages only roles below its own; a role higher up is out of its reach on purpose.
5. Set the `settings` rows `results_channel_id` and `content_channel_id` to the channels the cards go to. Before a write test against staging, point them at a test channel; a staging row may name a live channel.
6. Add the Discord role bindings under Config > Discord roles. New bindings start ignored; mark one synced to let the button manage it.

# Facts

- The guild the backend reads is a maintainers' decision. Changing it needs new role ids in the bindings.
- The bot's token can read a channel over REST; it cannot write forum tags without Manage Threads.
- Test posts to a test channel use `allowed_mentions: {"parse": []}` so nobody is pinged.
