---
type: Domain Concept
title: Roles and permissions
description: Four roles decided by the database and the guild, ownership checked per row, reads open and writes admin-only, and an admin view-as switch.
resource: ../../../app/api/deps.py
tags: [auth]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-19T00:00:00Z }
sources:
  - id: deps
    resource: ../../../app/api/deps.py
    title: The claims and the guards
  - id: admins
    resource: ../../../app/services/admins.py
    title: Who administers the site
  - id: roles
    resource: ../../../app/services/discord_roles.py
    title: The roles the database says an account earns
---

# The four roles

| Role | Who | How it is decided |
|---|---|---|
| guest | a Discord account that is not in the WC3 Gym guild | the bot reads the guild; no `DISCORD_BOT_TOKEN` means everyone is a guest |
| member | an account in the guild | the guild read |
| captain | a member with a seat in `team_season_captain` for a running season | the database, live on every request |
| admin | a row of `admin_grant`, or an id in `ADMIN_DISCORD_IDS` | the database; the environment ids are the bootstrap and cannot be revoked |

Discord grants nothing: the guild owner, a role with the administrator bit and the old `admin_role` setting all read as members. `admin_role` stays a setting only because the old bot reads it. The super admin is the `ADMIN_TOKEN` login, a session with no Discord account, used by the admin UI's `/admin-login` page. See [authentication](../api/auth.md).

# Roles and ownership are two gates

A role is coarse and global. Ownership is checked per row: my profile, my availability, my soft blocks, a series I act for (the player a side names, a captain of the team that fields that side, or the roster of a side that names no player; an admin acts for either side), my fantasy team (the Fantasy Captain), my team's seat this season (a captain). Captain and Fantasy Captain are not roles you borrow; a route checks the seat or the owning row. Name a dependency for what it checks (ownership), not for who usually passes it.

Before writing a permission, write the user story ("As a member who owns a fantasy team, I place bets for my own team") and derive the check from it.

# Reads open, writes admin

Every GET serves any session, including a guest, unless it answers something personal. POST, PUT and DELETE keep `require_admin`, except a player's own self-service flows (signup, scheduling, reporting, veto, availability, fantasy), which are member-accessible and ownership-checked in the service. The frontend hides the buttons of admin writes rather than letting them fail: its fetch wrapper logs the session out on a 401. See [the decision](../decisions/reads-open-writes-admin.md).

# View as

An admin sends `X-View-As: captain|member|guest` to be treated as that role for the request, and `X-View-Seats: team:season,team:season` to name the seats of a viewed captain. The rewrite happens where every guard reads the role, so an admin viewing as a member meets the same 403s. `/me` answers `actual_role` so the switch stays visible.

# Discord roles are a mirror

The database is the source. A binding in `discord_role_binding` names a Discord role and a kind (`admin`, `captain`, `team`, `fantasy`, `gnl_participant`, `champion`) with a scope (`current`, `season`, `all`). A manual sync grants what is missing and takes back only bound roles the account no longer earns. Admin and coach roles are hand-managed in the guild and excluded from the sync. Sync is a button, never automatic. See [Discord integration](discord-integration.md) and [the decision](../decisions/app-managed-roles.md).
