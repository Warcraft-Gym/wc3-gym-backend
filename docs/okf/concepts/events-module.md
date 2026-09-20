---
type: Domain Concept
title: Events module
description: One data model for every kind of event, with GNL and KOTH behaviour in their own modules on top, a stage engine that never branches on kind, a phase derived on every read, and the admin's path from a new league to a finished event with awards.
resource: ../../../app/services/events.py
tags: [events]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-20T12:00:00Z }
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
  - id: gnl-events
    resource: ../../../app/services/gnl_events.py
    title: GNL event creation
  - id: home
    resource: ../../../app/services/home.py
    title: The home hub read
  - id: snapshot
    resource: ../../../tests/test_gnl_snapshot.py
    title: The GNL payloads pinned byte for byte
---

# One model

Every event kind shares the rows: `league`, `event`, `event_stage`, `event_round`, `event_division`, `event_entrant`, `matches` (fixtures), `series`, `series_side`, `series_game`. A GNL season is the `gnl` kind of event; it runs on the same tables and its payloads did not change when the tables were renamed. `tests/test_gnl_snapshot.py` pins those payloads, so a migration that shifts a GNL field fails before it reaches a page.

The rule that keeps this workable: **the shared engine never branches on kind.** A kind that needs different behaviour gets a kind module (`app/services/koth/`, and the GNL draft and fantasy services) and, where it needs its own columns, a side table. Never write `if kind == "gnl"` inside a shared service. See [the decision](../decisions/unified-event-model.md).

The event API is the canonical HTTP surface for every kind. `EventPublic` includes the GNL map pool, rounds, score configuration, fantasy configuration and unscored-series count. The two fields that exist only on `SeasonPublic`, `user_signup` and `signup_race`, describe the caller in a legacy response; event signup routes carry that state.

# Stages

`EventStage` names the format, the best-of, the map rules, the scheduling mode, the ranking rule and the advance count. Formats: `round_robin`, `gnl`, `single_elimination`, `double_elimination`, `swiss`, `koth`, `ffa`. A stage may split into groups that merge at the next stage; a division never merges.

The stage engine (`app/services/stage_engine.py`) generates the series of a stage, follows results through the feeder graph, and ranks the entrants. A `gnl` stage is drafted by its admin and its captains, so the engine refuses to generate one. A Swiss stage draws one round at a time. An `ffa` stage plays lobbies whose result is an order of places. A `koth` stage is a chain per division.

In a single elimination that plays a third-place series, that series decides places 3 and 4 and the final decides places 1 and 2; a beaten semi-finalist never ranks above the runner-up.

`app/services/series_rules.py` answers the rules one series plays under: a generated series reads them from its round, its stage and its event; a GNL series reads them from its season. The shape of the row decides, never the kind.

# Phase

An event's phase is derived on every read and never stored. The rungs, read from the last one back: `draft` while the event is unpublished; `finished` when an admin closed the event (`event.closed_at`), when the last stage by position holds series, every one of them is scored and the stage does not plan as a chain, or when the event has no series and its end has passed (its end date, else the day it starts); `running` once a series has started; `signups_open`; `checkin` while the check-in window of the next dated round is open; `seeded` otherwise. A scored stage with an empty stage after it reads `running`, so a cup whose playoff is still to be drawn is not finished. A chain grows while its admin names series, so a scored chain reads `running` until the close stamps the event. A list read answers the phase of a page of events from one grouped count, never one query per event.

# Entrants, seeds, divisions

An entrant is a player or a pre-made team in one event, with a race, a seed, a division, and eligibility warnings (`min_games`, `mmr_max`, a ban). Warnings show on the row and never refuse a signup. The games rule is one rule: `min_games` ladder games on the signup race, counted over the newest `min_games_seasons` W3C seasons where the event names a window and over every synced season where it does not. Seeds come from MMR, a shuffle, a hand order, the previous stage, a qualifier or an invitation. Seeding from a qualifier is not built: an event names the event it feeds through `parent_id`, and the seed write answers `not_built` until the parent reads its qualifiers' tables. An admin locks the seeds of a stage; a locked stage refuses a seed write. A seed from the previous stage and the advance to the next stage read one order, and both refuse with a 400 while any series of that stage has no result.

Divisions cut the entrant pool by MMR (`app/core/divisions.py`). Every division runs the same stage list on its own; a merged playoff across divisions is never a rule in the app.

# Signup policy

`signup_policy` is `members` (a member with an account) or `anyone` (any battle tag; KOTH takes signups from Twitch chat this way). A per-event switch allows one entrant row per race, off by default, on for KOTH nights.

An event of a league that drafts its teams (`entrant_kind` is `drafted_teams`) takes no direct signup, and the write refuses it by that shape, never by the event kind. A captain of a team may enter that team into an event of the same league. A cross-league team is refused. The entrant cap refuses a signup past it and no waiting list is kept.

# The home hub read

`GET /home/series` is the one read behind the home page's series panels, and it
crosses every kind: a GNL fixture, a cup bracket and a KOTH night answer side by
side. It needs no token. It holds three lists, `next` (the five soonest booked
series with no result), `casts_upcoming` (three of those a caster has claimed)
and `casts_recent` (the four newest played series whose cast carries a VOD). A
draft pairing and an event that is not published never appear. Each row carries
what a card prints and nothing more: the label in parts (`league`, `event`,
`stage`, `round`), the two fixture teams, each side as id, name, country, the
race the row names and one rating, the two map scores, and one cast with its
link. An empty field is left out of the row, so a reader defaults a missing key
to null. The answer is cacheable at the edge for two minutes and stays under
four kilobytes. It costs a fixed number of statements, none of them per row.

# Awards

Closing an event freezes the table of its last stage into `event_award`, one row per placed entrant per division. A trophy read lists a cup win or a KOTH crown from those rows without replaying the stage.

# Discord card

Every event has one card the app posts and edits in Discord, with a sign-up, a withdraw and a check-in button. A press writes through the same entrant service the site uses. The check-in button is enabled only while the event's check-in window is open, which the full event read answers as `checkin_open`; a press outside the window answers that the check-in is not open yet, or that it has closed. See [Discord integration](discord-integration.md).

# Managing an event

The admin's path from a new league to a finished event, in order. Every write here needs an admin unless the step says otherwise; the frontend repository owns the pages.

1. **Create the league.** `POST /leagues` with the name, the short name, the `kind` and the `entrant_kind`. `PUT /leagues/{id}` changes it later. The GNL and the KOTH league already exist.
2. **Create the event.** `POST /events` with the league id, fields and optional stage list. A GNL league dispatches to its kind service, which writes one `gnl` stage, the requested rounds, the ordered map pool and the achievement rules in the same transaction. The caller does not also send `kind=gnl`; the league selects those rules and the default already has that value. A generic event body without `stages` gets one default stage; an explicit empty list gets none, which is a signup-only event. `entrant_kind` left out is copied from the league. `PUT /events/{id}` changes the fields; an event that already holds teams must remove them before its league can change. `PUT /events/{id}/stages` replaces the stage list in play order, updating a stage in place so its rounds and series stay, and refusing to drop a stage that still holds rounds. A KOTH night is opened in one call, `POST /koth/nights`, which writes the event, its `koth` stage and its three brackets.
3. **Publish.** `PUT /events/{id}` with `published` on. A draft reads for an admin only and its phase is `draft`.
4. **Open signups.** `PUT /events/{id}` with `signups_open` on; the phase reads `signups_open`. A finished event answers `signups_open` false on every read and refuses a signup. `POST /events/{id}/discord-post` posts the event card with its buttons in a channel, or edits the card already there.
5. **Entrants.** A member signs up with `POST /events/{id}/entrants`, a captain enters their team the same way, an admin enters anyone with `POST /events/{id}/entrants/admin` whether signups stand open or not, and a Twitch chat command enters a battle tag through `GET /koth/signup`. `DELETE /events/{id}/entrants/me` withdraws and keeps the row, every row of the caller or the one race a `race` query parameter names; `DELETE /events/{id}/entrants/{entrant_id}` removes it. `POST /events/{id}/entrants/{entrant_id}/checkin` checks an entrant in on an event with no dated round; an event with dated rounds checks in per round through `PUT /player-availability`. `GET /events/{id}/entrants` lists every row with its MMR and its warnings. `entrant_count` on the event and on each division counts players, so two races of one player count once.
6. **Divisions.** `PUT /events/{id}/divisions` replaces the list, strongest first, clears every placement and clears the division off every series and match that named one. `POST /events/{id}/divisions/assign` cuts the live entrants by the MMR of their signup race, leaving hand-placed ones alone; a hand-placed entrant takes one of its division's seats, so a sized division never holds more than its size. `PUT /events/{id}/entrants/{entrant_id}` moves one entrant by hand.
7. **Seeds and the lock.** `PUT /events/{id}/stages/{stage_id}/seeds` numbers the entrants 1..n inside each division from a `source`: `mmr`, `random`, `manual` with an `order`, `invitation`, or `previous_stage`, which reads the standings of the stage before and refuses while a series of it has no result. `POST /events/{id}/stages/{stage_id}/seeds/lock` stamps the stage; a locked stage refuses a seed write.
8. **Generate.** `POST /events/{id}/stages/{stage_id}/generate` writes every series of the stage from the seeds, one bracket per division, and refuses a `gnl` stage and a stage that already holds series. A stage that draws by round (`swiss`, `koth`) takes `POST /events/{id}/stages/{stage_id}/rounds` once per round. `POST /events/{id}/stages/{stage_id}/series` appends a challenger to a chain. On a team event, `POST /events/{id}/stages/{stage_id}/fixtures/{fixture_id}/template` writes the ordered series one fixture holds, and a captain fills a side's roster with `PUT /series/{id}/sides`. A GNL season is not generated: its fixtures come from the match routes and its series from the captains' drafts.
9. **Results.** The player a side names, a captain of its team, a member of the roster a side that names no player fields, or an admin reports through `PUT /player-series/{id}`; `PUT /series/{id}/result-kind` records a walkover or a forfeit; `PUT /series/{id}/places` enters the order of an FFA lobby. A score follows the feeder graph into the next series by itself. `GET /events/{id}/stages/{stage_id}/series` and `GET /events/{id}/stages/{stage_id}/standings` read the run and the table; both are open reads. A stage series row carries a reduced player, which holds no W3Champions stats, so the row names the rating of each side on the race it plays in `player1_mmr` and `player2_mmr`; the whole list is rated in two statements, three while the W3Champions season setting is unset, and a side with no rating on that race reads null.
10. **Advance.** `POST /events/{id}/stages/{stage_id}/advance` seeds the next stage from the top places of every division's table and refuses on the last stage or while a series has no result. A stage with `auto_advance` does this on its last score.
11. **Finish and awards.** `POST /events/{id}/finish` writes the `event_award` rows from the table of the last stage, one per placed entrant per division; a second call rewrites them. A KOTH night closes with `POST /koth/nights/{id}/close`, which deletes the series nobody played and then pays the awards. [Phase](#phase) lists when the event reads `finished`.
