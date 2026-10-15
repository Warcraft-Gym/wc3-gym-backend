---
type: Decision
title: Cup teams live for one cup
description: A team of a team cup is made for that cup alone, signed up by its captain and confirmed by every player; it lives in the cup's own tables and no league reads it.
tags: [events, teams]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-15T11:30:00Z }
sources:
  - id: source
    resource: Maintainers' decisions, 2026-10-08
    title: Team cups
  - id: service
    resource: ../../../app/services/cup_teams.py
    title: The cup team routes
---

# Decision

Since 2026-10-08, a team cup (`event.team_size` 2 to 4) plays real team games, all players of a side on one map. Its teams are [cup_team](../data/tables/cup_team.md) rows of the cup: a captain signs one up, every other player confirms an invitation, and a runner may enter a whole team by hand or swap a player until the team has played. Every player is held to the cup's eligibility on their own, and any member of the team checks it in, vetoes and reports.

# Why

Community team cups are played by pairs and fours who come together for an evening. A team that lives only as long as its cup needs no page of its own and no rules for changing its players between cups. The team lives in the cup's own tables, so no GNL rule reaches it: see [cups keep their own tables](cups-own-tables.md).

# Consequences

- A cup team holds no `teams` row, no captain seat and no season roster; the GNL captain claims, stats, trophies and Discord roles never read it.
- A team's members ([cup_team_member](../data/tables/cup_team_member.md)) are confirmed players only; an invited player waits in [cup_team_invite](../data/tables/cup_team_invite.md).
- The draw refuses while a team of the cup is short of players, and names the teams.
- A player picks no race for a team cup; eligibility reads the races they have really played, see [the events module](../concepts/events-module.md#entrants-seeds-divisions).
