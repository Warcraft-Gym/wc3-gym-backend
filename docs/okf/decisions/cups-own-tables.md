---
type: Decision
title: Cups keep their own tables
description: A cup's series and teams live in tables of their own, beside GNL's series and team tables, and carry only what a cup uses.
tags: [events, series, teams, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-15T11:57:00Z }
sources:
  - id: source
    resource: Maintainers' decision, 2026-10-12
    title: Separate tables for cup series and cup teams
  - id: migration
    resource: ../../../migrations/versions/a8e3c5f1d276_give_the_cups_their_own_tables.py
    title: The migration that made the tables
  - id: engine
    resource: ../../../app/services/cup_engine.py
    title: The cup engine
---

# Decision

Since 2026-10-12, a cup plays on its own tables: [cup_series](../data/tables/cup_series.md) with [cup_series_game](../data/tables/cup_series_game.md), [cup_veto_step](../data/tables/cup_veto_step.md) and [cup_series_side](../data/tables/cup_series_side.md), and [cup_team](../data/tables/cup_team.md) with [cup_team_member](../data/tables/cup_team_member.md) and [cup_team_invite](../data/tables/cup_team_invite.md). The cup engine and the `/cup-series` routes read and write them; GNL and KOTH keep `series`, `teams` and their seasons' rosters. The tables carry only what a cup uses today: no fixture, host, cast, replay, fantasy mark or Discord card.

# Why

A cup on the GNL tables would run every GNL rule, the captain check, the stats and the Discord roles among them, and a GNL rule cannot reach a row it never reads.

# Consequences

- One permission rule answers every cup write: a player of a side, or a runner of the cup. See [events module](../concepts/events-module.md#cup-series).
- A cup series shows on the cup's pages and in the caller's own list on Home (`GET /me/cup-series`): no player history, head-to-head or Discord card reads it. Adding one is a change of its own.
- A cup enters the teams made for it and no league team, and a round robin over its teams writes one series per pair, with no fixture.
- The engine is split by table, never by kind: the cup engine on the cup tables, the stage engine on `series` for KOTH and GNL. Both read the same plans in `app/core/brackets.py` and the same result rules in `app/core/outcome.py`.
- A cup holds no row in `series` or `teams`.
