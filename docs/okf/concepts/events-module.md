---
type: Domain Concept
title: Events module
description: One data model for every kind of event, with GNL and KOTH behaviour in their own modules on top, a stage engine that never branches on kind, a phase derived on every read, and the admin's path from a new league to a finished event with awards.
resource: ../../../app/services/events.py
tags: [events]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-06T13:49:37Z }
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
---

# One model

Every event kind shares the rows: `league`, `event`, `event_stage`, `event_round`, `event_division`, `event_entrant`, `matches` (fixtures), `series`, `series_side`, `series_game`. A GNL season is the `gnl` kind of event; it runs on the same tables and its payloads did not change when the tables were renamed. `tests/test_event_season_parity.py` pins the GNL fields on `EventPublic`.

The rule that keeps this workable: **the shared engine never branches on kind.** A kind that needs different behaviour gets a kind module (`app/services/koth/`, and the GNL draft and fantasy services) and, where it needs its own columns, a side table. Never write `if kind == "gnl"` inside a shared service. See [the decision](../decisions/unified-event-model.md).

The event API is the canonical HTTP surface for every kind. `EventPublic` includes the GNL map pool, rounds, score configuration, fantasy configuration and unscored-series count. `user_signup` exists only on `SeasonPublic` and is always empty; `signup_race` and `played_as` are always null there. A user's `signup_seasons` entries are `SeasonSummaryPublic` and carry that signup's `signup_race` and `played_as` (see [response shapes](../api/response-shapes.md)); event signup routes carry the caller's signup state.

# Stages

`EventStage` names the format, the best-of, the map rules, the scheduling mode, the ranking rule and the advance count. Formats: `round_robin`, `gnl`, `single_elimination`, `double_elimination`, `swiss`, `koth`, `ffa`. A stage may split into groups that merge at the next stage; a division never merges.

The stage engine (`app/services/stage_engine.py`) generates the series of a stage, follows results through the feeder graph, and ranks the entrants. A `gnl` stage is drafted by its admin and its captains and a `koth` stage is paired by its admin during the night, so the engine refuses to generate either. A Swiss stage draws one round at a time. An `ffa` stage plays lobbies whose result is an order of places. A `koth` stage is a chain per division.

In a single elimination that plays a third-place series, that series decides places 3 and 4 and the final decides places 1 and 2; a beaten semi-finalist never ranks above the runner-up.

`app/services/series_rules.py` answers the rules one series plays under: a generated series reads them from its round, its stage and its event; a GNL series reads them from its season. The shape of the row decides, never the kind.

# Phase

An event's phase is derived on every read and never stored. The rungs, read from the last one back: `draft` while the event is unpublished; `finished` when an admin closed the event (`event.closed_at`), when the last stage by position holds series, every one of them is scored and the stage does not plan as a chain, or when its end date has passed, or, for an event with no end date and no series, when the day it starts has passed; `running` once a series has started; `signups_open`; `checkin` while the check-in window of the next dated round is open; `seeded` otherwise. A scored stage with an empty stage after it reads `running`, so a cup whose playoff is still to be drawn is not finished. A chain grows while its admin names series, so a scored chain reads `running` until the close stamps the event. An event whose teams are drafted (`entrant_kind` is `drafted_teams`) is finished by the close alone: its series are drafted round by round, so neither the last result it holds nor its end date ends it. A list read answers the phase of a page of events from one grouped count, never one query per event.

# The list reads

`GET /events` and the events of `GET /leagues/{league_id}` read newest start first: by the start time, else the start date, with an event that has neither last and the newer id first on a tie. The order and the page are cut in SQL. Both reads take `archived`: `false` leaves out every event that has a [koth_history_event](../data/tables/koth_history_event.md) row, `true` keeps only those, and no value keeps both. Each listed event carries `archived`: `true` when it has that row, else `false`, read as a column of the page statement. `POST /events/search` carries it the same way. `X-Total-Count` on `GET /events` counts the filtered set.

# The member read

`GET /me/events` answers one row per published event that is not an archived KOTH night, with the caller's own state on it: the entrant, the race of every live entrant row of the caller in `entrant_races` (an event that takes one entry per race holds one row per race, and a caller who is not entered reads an empty list), the check-in shape and its window, the next dated round, the phase and the one action the page offers. A caller who holds a captain seat in the event also gets `captain_fixture`: the own team's fixture of the next round that still has places left, with the two teams, the round's dates, `series_per_round` and the counts of published series, played series and open drafts, so the home page links the round draft before the fixture holds any series. While the event is not closed, the same caller gets `captain_matches`: every fixture of that team in the event, in round order and in the same shape, so the home page leads to the team's match of any round, drafted or not, running or over. Every other caller reads null and an empty list. The whole list costs a fixed number of statements whatever it holds, six of them for the captain fixtures; it loads only the event columns a row uses and only the rounds that are not over or have no dates.

# Entrants, seeds, divisions

An entrant is a player or a pre-made team in one event, with a race, a seed, a division, and eligibility warnings (`min_games`, `mmr_max`, a ban). Warnings show on the row and never refuse a signup. The games rule is one rule: `min_games` ladder games on the signup race, counted over the live W3C window, the current season and the one before it, or over the current season alone where `min_games_seasons` is 1. Seeds come from MMR, a shuffle, a hand order, the previous stage, a qualifier or an invitation. Seeding from a qualifier is not built: an event names the event it feeds through `parent_id`, and the seed write answers `not_built` until the parent reads its qualifiers' tables. An admin locks the seeds of a stage; a locked stage refuses a seed write. A seed from the previous stage and the advance to the next stage read one order, and both refuse with a 400 while any series of that stage has no result.

Divisions cut the entrant pool by MMR (`app/core/divisions.py`). A band list that names a lower bound for every band takes no entrant without a rating: that entrant stays unplaced until an admin places it. Every division runs the same stage list on its own; a merged playoff across divisions is never a rule in the app.

# Signup policy

`signup_policy` is `members` (a member with an account) or `anyone` (any battle tag; KOTH takes signups from Twitch chat this way). A per-event switch allows one entrant row per race, off by default, on for KOTH nights.

An event of a league that drafts its teams (`entrant_kind` is `drafted_teams`) takes no direct signup, and the write refuses it by that shape, never by the event kind. A captain of a team may enter that team into an event of the same league. A cross-league team is refused. The entrant cap refuses a signup past it and no waiting list is kept.

# The home hub read

`GET /home/series` is the one read behind the home page's series panels, and it
crosses every kind: a GNL fixture, a cup bracket and a KOTH night answer side by
side. It needs no token. It holds three lists, `next` (the five soonest booked
series), `casts_upcoming` (three of those a caster has claimed)
and `casts_recent` (the four newest played series whose cast carries a VOD). A
booked series is one with no result whose start is no more than two hours past,
so a series that is being played right now still has a card and leads the list. A
draft pairing and an event that is not published never appear. Each row carries
what a card prints and nothing more: the label in parts (`league`, `event`,
`stage`, `round`), the two fixture teams, each side as id, name, country, the
race the row names and one rating, the two map scores, and one cast with its
link. An empty field is left out of the row, so a reader defaults a missing key
to null. The answer is cacheable at the edge for two minutes. Its worst case is
twelve fixture rows that each carry two team icon URLs; that body is about seven
and a half kilobytes raw and under four kilobytes compressed, which is what the
edge sends. It costs a fixed number of statements, none of them per row.

`GET /home/series/upcoming` is the page behind the hub's "All upcoming": every booked series of a published event in time order, at most 100, by the same rule as `next`. Each row is the hub row with every claim on it in `casts` in place of the one cast, so a caster claims, edits or leaves a cast from the list. It needs no token, is cacheable at the edge for two minutes, and costs the statements of one hub list, none of them per row.

# Awards

Closing an event freezes the table of its last stage into `event_award`, one row per placed entrant per division. A trophy read lists a cup win or a KOTH crown from those rows without replaying the stage.

# Discord card

Every event has one card the app posts and edits in Discord, with two buttons, Sign up and Check in. A press writes through the same entrant service the site uses. The check-in button is enabled only while the event's check-in window is open, which the full event read answers as `checkin_open`; a press outside the window answers that the check-in is not open yet, or that it has closed. See [Discord integration](discord-integration.md).

# Managing an event

The admin's path from a new league to a finished event, in order. Every write here needs an admin unless the step says otherwise; the frontend repository owns the pages.

1. **Create the league.** `POST /leagues` with the name, the short name, the `kind` and the `entrant_kind`. `PUT /leagues/{id}` changes it later. The GNL and the KOTH league already exist.
2. **Create the event.** `POST /events` with the league id, fields and optional stage list. A GNL league dispatches to its kind service, which writes one `gnl` stage, the requested rounds, the ordered map pool and the achievement rules in the same transaction. The caller does not also send `kind=gnl`; the league selects those rules and the default already has that value. A generic event body without `stages` gets one default stage; an explicit empty list gets none, which is a signup-only event. `entrant_kind` left out is copied from the league. `PUT /events/{id}` changes the fields; an event that already holds teams must remove them before its league can change. `PUT /events/{id}/stages` replaces the stage list in play order, updating a stage in place so its rounds and series stay, and refusing to drop a stage that still holds rounds. A KOTH night is opened in one call, `POST /koth/nights`, which writes the event, its `koth` stage and its three brackets.
3. **Publish.** `PUT /events/{id}` with `published` on. A draft reads for an admin only and its phase is `draft`.
4. **Open signups.** `PUT /events/{id}` with `signups_open` on; the phase reads `signups_open`. A finished event answers `signups_open` false on every read and refuses a signup. `POST /events/{id}/discord-post` posts the event card with its buttons in a channel, or edits the card already there.
5. **Entrants.** A member signs up with `POST /events/{id}/entrants`, a captain enters their team the same way, an admin enters anyone with `POST /events/{id}/entrants/admin` whether signups stand open or not, and a Twitch chat command enters a battle tag through `GET /koth/signup`. `DELETE /events/{id}/entrants/me` withdraws and keeps the row, every row of the caller or the one race a `race` query parameter names; `DELETE /events/{id}/entrants/{entrant_id}` removes it, except on a KOTH night, which removes a player on its run page. `POST /events/{id}/entrants/{entrant_id}/checkin` checks an entrant in on an event with no dated round; an event with dated rounds checks in per round through `PUT /player-availability`. `GET /events/{id}/entrants` lists every row with its MMR and its warnings. A signup that names a battle tag refuses one that is not shaped `Name#1234`, because the tag is the identity of a player with no account. `entrant_count` on the event and on each division counts players, so two races of one player count once.
6. **Divisions.** `PUT /events/{id}/divisions` replaces the list, strongest first, clears every placement and clears the division off every series and match that named one. `POST /events/{id}/divisions/assign` cuts the live entrants by the MMR of their signup race, leaving hand-placed ones alone; a hand-placed entrant takes one of its division's seats, so a sized division never holds more than its size. `PUT /events/{id}/entrants/{entrant_id}` moves one entrant by hand and gives it the last place in the line of its new division; a division whose king it was loses that king, because a division's king is a row of that division. A KOTH night refuses the division write and the cut, and refuses a move by hand once it is closed; see [KOTH night](koth.md).
7. **Seeds and the lock.** `PUT /events/{id}/stages/{stage_id}/seeds` numbers the entrants 1..n inside each division from a `source`: `mmr`, `random`, `manual` with an `order`, `invitation`, or `previous_stage`, which reads the standings of the stage before and refuses while a series of it has no result. `POST /events/{id}/stages/{stage_id}/seeds/lock` stamps the stage; a locked stage refuses a seed write. A KOTH night refuses a seed write, because its line is ordered on its run page.
8. **Generate.** `POST /events/{id}/stages/{stage_id}/generate` writes every series of the stage from the seeds, one bracket per division, and refuses a `gnl` stage, a `koth` stage and a stage that already holds series. A stage that draws by round (`swiss`, `koth`) takes `POST /events/{id}/stages/{stage_id}/rounds` once per round. `POST /events/{id}/stages/{stage_id}/series` appends a challenger to a chain. On a team event, `POST /events/{id}/stages/{stage_id}/fixtures/{fixture_id}/template` writes the ordered series one fixture holds, and a captain fills a side's roster with `PUT /series/{id}/sides`. A GNL season is not generated: its fixtures come from the match routes and its series from the captains' drafts.
9. **Results.** The player a side names, a captain of its team, a member of the roster a side that names no player fields, or an admin reports through `PUT /player-series/{id}`; `PUT /series/{id}/result-kind` records a walkover or a forfeit; `PUT /series/{id}/places` enters the order of an FFA lobby. A score follows the feeder graph into the next series by itself. `GET /events/{id}/stages/{stage_id}/series` and `GET /events/{id}/stages/{stage_id}/standings` read the run and the table; both are open reads. A stage series row carries a reduced player, which holds no W3Champions stats, so the row names the rating of each side on the race it plays in `player1_mmr` and `player2_mmr`: the `w3cstats` rating on a running event, the MMR of the time (`mmr_at`, see [Ladder and achievements](ladder-and-achievements.md)) on a finished one. Three reads tell the two apart; the running rows are rated in two statements, three while the W3Champions season setting is unset, and a finished event in one statement. A side with no rating on that race reads null.
10. **Advance.** `POST /events/{id}/stages/{stage_id}/advance` seeds the next stage from the top places of every division's table and refuses on the last stage or while a series has no result. A stage with `auto_advance` does this on its last score.
11. **Finish and awards.** `POST /events/{id}/finish` closes the event: it stamps `closed_at`, whatever results are still missing, and writes the `event_award` rows from the table of the last stage, one per placed entrant per division. A second call keeps the stamp and rewrites the rows. `POST /events/{id}/reopen` takes the close back: it clears the stamp, deletes the event's award rows and answers the event, which reads by its series again; an archived night refuses it. A KOTH night closes with `POST /koth/nights/{id}/close`, which deletes the series nobody played and then pays the awards. [Phase](#phase) lists when the event reads `finished`.
