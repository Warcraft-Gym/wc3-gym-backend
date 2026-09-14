---
type: Data Model
title: clerk_account
description: The Discord account behind one Clerk user, written on the first guarded request of a login so no later request asks Clerk.
resource: ../../../../app/models/clerk_account.py
tags: [auth, data]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T15:15:00Z }
verified: { by: process:test_okf, at: 2026-09-14T16:47:40Z }
sources:
  - id: model
    resource: ../../../../app/models/clerk_account.py
    title: ClerkAccount
  - id: deps
    resource: ../../../../app/api/deps.py
    title: The login dependency merges the row
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `clerk_user_id` | VARCHAR | no | Primary key. The Clerk user id of the session. |
| `discord_id` | VARCHAR | no | The Discord account id Clerk reports for that user. Rewritten when Clerk reports a different one. |

# Keys and joins

Primary key `clerk_user_id`. No foreign keys. `discord_id` matches [users](users.md) `discordId` by value, not by constraint, because a guest has a session and no player row.

# Rules

The row is a cache of Clerk's answer. No route reads or writes it directly. See [authentication](../../api/auth.md) and [the decision](../../decisions/clerk-auth.md).
