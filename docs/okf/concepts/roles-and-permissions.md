---
type: Domain Concept
title: Roles and permissions
description: Four roles decided by the database and the guild, ownership checked per row, reads open and writes admin-only, and an admin view-as switch.
resource: ../../../app/api/deps.py
tags: [auth]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-07T20:00:00Z }
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
| guest | a Discord account that is not in the WC3 Gym guild | the bot reads the guild; with no `DISCORD_BOT_TOKEN` the check cannot run, and a login that is not an admin is refused with 502 |
| member | an account in the guild | the guild read |
| captain | a member with a seat in `team_season_captain` for a season that is not closed | the database, live on every request |
| admin | a row of `admin_grant`, or an id in `ADMIN_DISCORD_IDS` | the database; the environment ids are the bootstrap and cannot be revoked |

An admin who also holds a captain seat keeps the role `admin` and carries the `seats` list as well, so `/me` names the teams that admin captains. Every guard already admits an admin, so the seats change one answer: the draft `seen` stamp and the seen-at of the draft state read the caller's seat, so an admin who captains writes and reads them for the team held.

Discord grants nothing: the guild owner, a role with the administrator bit and the old `admin_role` setting all read as members. `admin_role` stays a setting only because the old bot reads it. The super admin is the `ADMIN_TOKEN` login, a session with no Discord account, used by the admin UI's `/admin-login` page. See [authentication](../api/auth.md).

# Roles and ownership are two gates

A role is coarse and global. Ownership is checked per row: my profile, my availability, my soft blocks, a series I act for (the player a side names, a captain of the team that fields that side, or the roster of a side that names no player; an admin acts for either side), my fantasy team (the Fantasy Captain), my team's seat this season (a captain). Captain and Fantasy Captain are not roles you borrow; a route checks the seat or the owning row. Name a dependency for what it checks (ownership), not for who usually passes it.

Before writing a permission, write the user story ("As a member who owns a fantasy team, I place bets for my own team") and derive the check from it.

# Organizers

An organizer is not a fifth role. It is a capability a guild member holds beside its role, so the member and captain guards stay as they are.

- **Who.** A Discord account with an [organizer_grant](../data/tables/organizer_grant.md). It needs no player row, only a Discord login. The grant counts while the account is a guild member acting as itself: a guest, the admin token and an admin viewing as a lower role hold none. `/me` answers `organizer` and `organizer_request`. The check runs on the routes that need it, never on every request.
- **A drawn cup.** The event's runners take a draw back (`DELETE /events/{id}/stages/{stage_id}/series`) and swap a player who has not played (`POST /events/{id}/entrants/{entrant_id}/replace`); both are event writes `require_event_runner` guards.
- **Maps.** An organizer reads `GET /maps/ladder-import` to fill a cup's pool from the 1v1 ladder, and writes the pool of an event it runs with `PUT /events/{id}/maps`. Creating or changing a map stays the admins'.
- **Becoming one.** A member sends `POST /organizers/requests` with an optional note. An admin approves or declines it under Admin › Access, or grants an account directly by Discord id. See [organizer_request](../data/tables/organizer_request.md).
- **What a grant allows.** `POST /events` for a small event: a `cup` or `signup` kind, of no league or a `custom` league, with no event Discord role, no `gnl` or `koth` stage, and a parent only among the events it runs. An admin writes any event.
- **Running an event.** An [event_organizer](../data/tables/event_organizer.md) row lets its account run that one event: every event write `require_event_runner` guards, the event's series results (`PUT /player-series/{id}`, where it acts for either side as an admin does; `PUT /series/{id}/result-kind`; `PUT /series/{id}/places`), its co-organizers, and its draft, which it reads as an admin does. The row outlives a revoked grant. A GNL season and a KOTH night never hold a row, so their writes stay the admins'. Posting the event card in a Discord channel stays an admin's.

# Reads open, writes admin

Every GET serves any session, including a guest, unless it answers something personal. POST, PUT and DELETE keep `require_admin`, except the writes on one event, which its organizers make as well (see [organizers](#organizers)), a player's own self-service flows (signup, their own battle tags, scheduling, reporting, veto, availability, fantasy), which are member-accessible and ownership-checked in the service, and a captain's team flows, checked against the seat: the round answers of their own roster, the draft of a fixture their team plays, which either captain of that fixture writes and publishes, and the published series of that fixture: adding one up to the round's series, editing its time, result, races played, host and fantasy mark, and deleting one. These routes check the seats the session carries, as the draft routes do (`own_match` in `app/api/deps.py`). Two more writes are open: a member claims a series to cast (`POST /series/{id}/casts`), and the claim's owner or an admin changes or removes it; a captain names the roster of their own side of a fixture series (`PUT /series/{id}/sides` with `sides`), where the service checks the seat. The frontend hides the buttons of admin writes rather than letting them fail: its fetch wrapper logs the session out on a 401. See [the decision](../decisions/reads-open-writes-admin.md).

# View as

An admin sends `X-View-As: captain|member|guest` to be treated as that role for the request, and `X-View-Seats: team:season,team:season` to name the seats of a viewed captain. A view-as request drops the admin's own seats, so a viewed member holds none and a viewed captain holds only the seats the header names. The rewrite happens where every guard reads the role, so an admin viewing as a member meets the same 403s. `/me` answers `actual_role` so the switch stays visible.

# Discord roles are a mirror

The database is the source. A binding in `discord_role_binding` names a Discord role and a kind (`admin`, `captain`, `team`, `fantasy`, `gnl_participant`, `champion`) with a scope (`current`, `season`, `all`). A manual sync grants what is missing and takes back only bound roles the account no longer earns. Admin and coach roles are hand-managed in the guild and excluded from the sync. Sync is a button, never automatic. See [Discord integration](discord-integration.md) and [the decision](../decisions/app-managed-roles.md).
