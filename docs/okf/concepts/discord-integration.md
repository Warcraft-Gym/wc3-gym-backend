---
type: Integration
title: Discord integration
description: Slash commands arrive through a separate adapter and are checked and answered here, cards are posted and edited under a rate limit, and season roles are mirrored to the guild on a button press.
resource: ../../../app/services/interactions.py
tags: [discord]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: interactions
    resource: ../../../app/services/interactions.py
    title: The interactions the adapter forwards, and the command list
  - id: posts
    resource: ../../../app/services/discord_posts.py
    title: The posts the app keeps true
  - id: discord
    resource: ../../../app/services/discord.py
    title: The Discord calls and the guild read
  - id: roles
    resource: ../../../app/services/discord_roles.py
    title: The role sync
  - id: cards
    resource: ../../../app/services/series_cards.py
    title: The series cards
---

# The contract with the adapter

Discord sends every slash command, button press and autocomplete to a small adapter in the repository `wc3-gym-discord-bot`. The adapter checks Discord's Ed25519 signature, answers inside Discord's 3 second window with a deferred private reply, and forwards the payload unchanged to `POST /discord/interactions` with the same two headers, `X-Signature-Ed25519` and `X-Signature-Timestamp`. This route checks the signature again with `DISCORD_PUBLIC_KEY`, so it trusts Discord and nothing else, then runs the command and replies through the interaction token: a private edit of the deferred reply, or a public follow-up in the channel. The route answers 503 while `DISCORD_PUBLIC_KEY` is unset. Autocomplete has no deferred form; the adapter waits 2 seconds and answers an empty list on a timeout.

The adapter holds no bot token and knows no command. The command list lives here, in `COMMANDS` in `app/services/interactions.py`, and `uv run just discord-commands` registers it on the guild.

# The commands

| Command | What it does |
|---|---|
| `/upcoming` | the series scheduled in the next days, claimed first |
| `/leaderboard` | achievement, ladder or fantasy points this season |
| `/achievements` | a player's badges |
| `/stats` | one player's GNL season from the stored ladder and their series |
| `/announce` | the match card of one series, posted in the channel |
| `/availability` | a card for one round with one button per answer |
| `/schedule` | set the time of the caller's series |
| `/score` | report a result with one replay per game, through the same write the dashboard uses |
| `/veto` | point the two players at the veto board and say where it stands |
| `/postlinks` | the site's links as buttons, posted by an admin |

Each command is one module under `app/services/commands/`. A module imports `base.py`, never `interactions.py`, which imports the modules.

# Cards and posts

The app posts a result card, a cast claim card and a start reminder, plus one card per event with sign-up and withdraw buttons. Each post is a `discord_post` row so the app can edit it later. The channels come from the `settings` rows `results_channel_id` and `content_channel_id`; a missing row means no card.

Discord allows five edits per five seconds per channel. `discord_posts.refresh_series` claims an edit with one UPDATE, waits when the channel had an edit in the last second, and skips a post already edited after its latest change, so a burst collapses to the last state. `discord._channel_call` waits out one 429. Never loop edits per write, and never use an in-memory queue or lock: no process survives a request on Vercel. See [the decision](../decisions/discord-rate-limit.md).

Card rules: a mention is a call to action, so `/upcoming` tags nobody and the reminder tags the casters and the players; no database ids on a card; the round number, not the week; a player reads `{flag} {name} ({race} {mmr})` with the race played, else the signup race; every time is a Discord timestamp; the veto shows what the season's `map_rules` say.

# The guild read and the roles

An account's Discord token from Clerk only identifies it; the bot token reads the guild membership. `DISCORD_GUILD_ID` names the guild. Which guild it names is a maintainers' decision, never a configuration fix for a guest classification.

`discord_role_binding` maps a role kind and scope to a guild role. `POST /config/discord-roles/sync` grants and revokes season roles; it never touches admin or coach roles, and it runs only when an admin presses the button. The bot's role must sit directly above the season roles in the guild's role list and below everything else, because a bot manages only roles below its own. See [roles](roles-and-permissions.md).

# Reading a Discord link

A session cannot open a `discord.com/channels/...` link, but the REST API with the bot token reads a channel or thread: `GET /channels/{id}/messages?limit=50`. The bot token is an environment value.
