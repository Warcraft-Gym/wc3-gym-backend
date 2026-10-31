---
type: Data Model
title: clerk_account
description: The Discord account behind one Clerk user, from when Clerk signed members in; no code reads or writes it, and a later release drops it.
resource: ../../../../app/models/clerk_account.py
tags: [auth, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-27T12:00:00Z }
verified: { by: process:test_okf, at: 2026-09-14T17:40:50Z }
sources:
  - id: model
    resource: ../../../../app/models/clerk_account.py
    title: ClerkAccount
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `clerk_user_id` | VARCHAR | no | Primary key. The Clerk user id of the session. |
| `discord_id` | VARCHAR | no | The Discord account id Clerk reports for that user. Rewritten when Clerk reports a different one. |

# Keys and joins

Primary key `clerk_user_id`. No foreign keys. `discord_id` matches [users](users.md) `discordId` by value, not by constraint, because a guest has a session and no player row.

# Rules

No code reads or writes the table. A migration drops it in a release after the one whose code stopped reading it is live, as [the migration rule](../../conventions/git-and-pull-requests.md) says.
