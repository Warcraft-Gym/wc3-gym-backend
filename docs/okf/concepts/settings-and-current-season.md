---
type: Domain Concept
title: Settings and the current season
description: A key-value table holds the few runtime values an admin edits, including the two season pointers, and a missing row falls back to the newest season.
resource: ../../../app/services/settings.py
tags: [api]
generated: { by: claude-code/claude-opus-5-5, at: 2026-09-26T14:40:00Z }
sources:
  - id: settings
    resource: ../../../app/services/settings.py
    title: SettingsService
  - id: config-routes
    resource: ../../../app/api/routes/config.py
    title: The config routes
  - id: readme
    resource: ../../../README.md
    title: The settings paragraph under "Know the environment variables"
---

# The rows

| Key | Read by | When missing |
|---|---|---|
| `current_gnl_season` | the captain check, the role sync, the public signup form, the player history, the Discord bot | the newest season |
| `current_w3c_season` | the live MMR window, that season and the one before it, and the ladder sync | the ratings read the newest season stored in `w3cstats`; the ladder sync reads the newest season from the API |
| `w3c_url` | the W3Champions client; wins over the `W3C_URL` variable | the variable, then the default |
| `KOTH_NIGHTBOT_TOKEN` | the Twitch chat signup | the signup answers 401 |
| `results_channel_id` | the result card | no card |
| `content_channel_id` | the cast claim and reminder cards | no card |
| `admin_role` | the old bot only; it grants nothing here | nothing |
| `fantasy_team_creation_enabled` | a hand override of the fantasy creation lock | the phase rule alone |

Before adding a key for the bot, read `GET /config/settings` and reuse a row with the same purpose; the old bot left rows such as `scheduling_channel_id` behind, and a staging row may name a live channel, so point a test write at a test channel first.

# What is not a setting

- Site admins are rows of `admin_grant`, edited under Config > Access, with `ADMIN_DISCORD_IDS` as the bootstrap.
- Discord role bindings are rows of `discord_role_binding`.
- `signups_open`, `scheduling_enabled` and `checkin_enabled` are columns on the season, one switch per event.
- The season's phase is derived and never stored.

# The W3Champions season pin stays

The derived default is wrong on the one day it matters: when a new W3Champions season opens, a blank pin follows it at once and every player reads as zero games. A stored value is a deliberate choice and must keep winning over the derived one. Never propose auto-following the latest season, a staleness warning, or clearing the row. The seasonal hand edit is an accepted cost. See [the decision](../decisions/season-boundary-manual.md).

# Routes

`GET /config/settings` and `GET /config/settings/{key}` are open reads. `PUT /config/settings`, `PUT /config/settings/{key}` and `DELETE /config/settings/{key}` are admin writes. `GET /config/w3c` shows the URL and season the backend resolved. `POST /config/koth/nightbot-token` generates the Twitch token.
