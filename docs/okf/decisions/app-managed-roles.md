---
type: Decision
title: App-managed roles, manual sync
description: Access comes from the database, Discord roles are a mirror of season facts, and the mirror updates only when an admin presses a button.
tags: [auth]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: source
    resource: Maintainers' decisions, 2026-08-30 to 2026-09-03
    title: App-managed roles
---

# Decision

An admin is a database grant or a bootstrap id. A captain is a seat. Discord grants nothing: the guild owner, the administrator bit and the old admin role setting all read as members. Season-specific Discord roles (team, captain, participant, fantasy, champion) are bound to guild roles and synced on a button press; admin and coach roles are hand-managed in the guild and outside the sync.

# Why

Access must not depend on Discord roles, and an automatic sync would churn people's Discord roles while an admin is still reassigning teams.

# Consequences

- Never add a Discord read that grants a role. A new role is a binding kind plus a database fact.
- Never make the sync automatic, and never let it touch admin or coach roles.
- A binding carries a scope: current season, one season, or all seasons. Teams and captains default to all, players and fantasy to current, champions to one season.
- The sync grants and revokes only the bound season roles. A role shared with people who hold no seat needs an additive-only binding before it is synced.
