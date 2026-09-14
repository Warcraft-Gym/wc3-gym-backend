---
type: Domain Concept
title: Events module
description: One data model for every kind of event, with GNL and KOTH behaviour in their own modules on top, a stage engine that never branches on kind, and a phase derived on every read.
tags: [events, architecture, domain]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T14:30:00Z }
sources:
  - id: events
    resource: ../../../app/services/events.py
    title: Leagues, events, stages and phase
  - id: engine
    resource: ../../../app/services/stage_engine.py
    title: The stage engine
  - id: rules
    resource: ../../../app/services/series_rules.py
    title: The rules one series plays under
  - id: snapshot
    resource: ../../../tests/test_gnl_snapshot.py
    title: The GNL payloads pinned byte for byte
---

# One model

Every event kind shares the rows: `league`, `event`, `event_stage`, `event_round`, `event_division`, `event_entrant`, `matches` (fixtures), `series`, `series_side`, `series_game`. A GNL season is the `gnl` kind of event; it runs on the same tables and its payloads did not change when the tables were renamed. `tests/test_gnl_snapshot.py` pins those payloads, so a migration that shifts a GNL field fails before it reaches a page.

The rule that keeps this workable: **the shared engine never branches on kind.** A kind that needs different behaviour gets a kind module (`app/services/koth/`, and the GNL draft and fantasy services) and, where it needs its own columns, a side table. Never write `if kind == "gnl"` inside a shared service. See [the decision](../decisions/unified-event-model.md).

# Stages

`EventStage` names the format, the best-of, the map rules, the scheduling mode, the ranking rule and the advance count. Formats: `round_robin`, `gnl`, `single_elimination`, `double_elimination`, `swiss`, `koth`, `ffa`. A stage may split into groups that merge at the next stage; a division never merges.

The stage engine (`app/services/stage_engine.py`) generates the series of a stage, follows results through the feeder graph, and ranks the entrants. A `gnl` stage is drafted by its admin and its captains, so the engine refuses to generate one. A Swiss stage draws one round at a time. An `ffa` stage plays lobbies whose result is an order of places. A `koth` stage is a chain per division.

In a single elimination that plays a third-place series, that series decides places 3 and 4 and the final decides places 1 and 2; a beaten semi-finalist never ranks above the runner-up.

`app/services/series_rules.py` answers the rules one series plays under: a generated series reads them from its round, its stage and its event; a GNL series reads them from its season. The shape of the row decides, never the kind.

# Phase

An event's phase is derived on every read and never stored. The rungs, read from the last one back: `draft` while the event is unpublished; `finished` when the last stage by position holds series and every one of them is scored, or when the event has no series and its end has passed (its end date, else the day it starts); `running` once a series has started; `signups_open`; `checkin` while the check-in window of the next dated round is open; `seeded` otherwise. A scored stage with an empty stage after it reads `running`, so a cup whose playoff is still to be drawn is not finished. A list read answers the phase of a page of events from one grouped count, never one query per event.

# Entrants, seeds, divisions

An entrant is a player or a pre-made team in one event, with a race, a seed, a division, and eligibility warnings (`min_games`, `mmr_max`, a ban). Warnings show on the row and never refuse a signup. Seeds come from MMR, a shuffle, a hand order, the previous stage, a qualifier or an invitation. An admin locks the seeds of a stage; a locked stage refuses a seed write. A seed from the previous stage and the advance to the next stage read one order, and both refuse with a 400 while any series of that stage has no result.

Divisions cut the entrant pool by MMR (`app/core/divisions.py`). Every division runs the same stage list on its own; a merged playoff across divisions is never a rule in the app.

# Signup policy

`signup_policy` is `members` (a member with an account) or `anyone` (any battle tag; KOTH takes signups from Twitch chat this way). A per-event switch allows one entrant row per race, off by default, on for KOTH nights.

An event of a league that drafts its teams (`entrant_kind` is `drafted_teams`) takes no direct signup, and the write refuses it by that shape, never by the event kind. A captain of a team may enter that team into any event of its league.

# Awards

Closing an event freezes the table of its last stage into `event_award`, one row per placed entrant per division. A trophy read lists a cup win or a KOTH crown from those rows without replaying the stage.

# Discord card

Every event has one card the app posts and edits in Discord, with a sign-up, a withdraw and a check-in button. A press writes through the same entrant service the site uses. The check-in button is enabled only while the event's check-in window is open, which the full event read answers as `checkin_open`; a press outside the window answers that the check-in is not open yet, or that it has closed. See [Discord integration](discord-integration.md).
