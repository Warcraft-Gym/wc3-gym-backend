---
type: Decision
title: Cup teams live for one cup
description: A team of a team cup is made for that cup alone, signed up by its captain and confirmed by every player; it names no league and stays out of the league team lists.
tags: [events, teams]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-08T18:00:00Z }
sources:
  - id: source
    resource: Maintainers' decisions, 2026-10-08
    title: Team cups
  - id: service
    resource: ../../../app/services/cup_teams.py
    title: The cup team routes
---

# Decision

Since 2026-10-08, a team cup (`event.team_size` 2 to 4) plays real team games, all players of a side on one map. Its teams are team rows with the cup as their `event_id`: a captain signs one up, every other player confirms an invitation, and a runner may enter a whole team by hand or swap a player until the team has played. Every player is held to the cup's eligibility on their own, and any player of the roster checks the team in, vetoes and reports.

# Why

Community team cups are played by pairs and fours who come together for an evening. A team kept beyond its cup would need a page of its own and rules for changing its players between cups, which nobody asked for; reusing the team row lets the engine, the veto and the report treat a cup team as any team entrant.

# Consequences

- `teams.league_id` is null for a cup team, which may name the cup's league or none; the league team lists leave rows with an `event_id` out.
- A team's roster holds confirmed players only; an invited player waits in [team_invite](../data/tables/team_invite.md).
- The draw refuses while a team of the cup is short of players, and names the teams.
- A player picks no race for a team cup; eligibility reads the races they have really played, see [the events module](../concepts/events-module.md#entrants-seeds-divisions).
