---
type: Pitfall
title: The guild setting is a decision, not a bug
description: A member classified as a guest is a membership question about the configured guild; changing the guild setting is a maintainers' decision, never a bug fix.
tags: [discord]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: source
    resource: ../../../app/services/discord.py
    title: The guild read
---

# The situation

A guest classification was read as a wrong guild setting, and the proposed fix was to change the setting. The setting is deliberate.

# The rule

`DISCORD_GUILD_ID` names the guild the membership check reads. Changing it is a maintainers' decision that also needs new role ids in the bindings. Treat "classified as guest" as "is this account in the configured guild".
