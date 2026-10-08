# Bundle history

## 2026-10-06

* **Update**: the KOTH history import reads each archived series on its own: a doubt leaves only that series without an inferred winner, a break has no winner and reads as `winner_left`, as does a written winner who does not play the next series, and a source note is shown in the page's words; a corrections key may keep its own spelling. [KOTH night](concepts/koth.md#historical-imports) and [koth_history_series](data/tables/koth_history_series.md) state it.
* **Update**: at a break in an archived KOTH bracket, where neither side plays on, the winner withdrew: the winner of the series before wins it when he plays in it, else it has no winner; the board row carries `winner_left`, and the throne is empty after it. [KOTH night](concepts/koth.md#historical-imports) and [koth_history_series](data/tables/koth_history_series.md) state it.
* **Update**: every `history` row of an archived KOTH bracket carries `throne` (`moved`, `held` or `none`), walked in play order from the written winner, else the inferred one, at no extra statement. [KOTH night](concepts/koth.md#historical-imports) states it.
* **Update**: the KOTH history import joins written names that fold to the same text in one bracket into one participant, and takes an optional corrections file of reviewed dates for undated nights and kept names for folded spellings; the stored source records stay as written. [KOTH night](concepts/koth.md#historical-imports) and [historical_participant](data/tables/historical_participant.md) state it.
* **Update**: every event of `GET /events`, `POST /events/search` and `GET /leagues/{league_id}` carries `archived`, true for an archived KOTH night and false for every other event, at no extra statement. [Events module](concepts/events-module.md#the-list-reads) states it.
* **Add**: `GET /koth/winners` lists every published, closed KOTH night, archived or run in the app, newest start first and paged by night, with the stored king of each bracket, in one statement and on the settled edge timer. [KOTH night](concepts/koth.md#the-winners-list) states it.
* **Update**: `GET /events` and `GET /leagues/{league_id}` list events newest start first (the start time, else the start date, undated last) and take `archived` to keep or drop the archived KOTH nights; `GET /me/events` and `GET /koth/events` leave archived nights out; the KOTH history import dates a night labelled with a month and a day but no year from its place on the source page. [Events module](concepts/events-module.md#the-list-reads) and [KOTH night](concepts/koth.md#historical-imports) state it.
* **Update**: every concept was read against the code. Among the corrections: every KOTH signup asks W3Champions, at most once an hour per tag, and the night has routes to add a played result and to clear every series; Git builds only `main` and `staging`; the API has 23 route modules and ten routes send `X-Total-Count`; ladder history starts at W3Champions season 11; the achievement catalogue holds 91 rules; a captain's seat counts in every season that is not closed. [KOTH](concepts/koth.md), [the API overview](api/overview.md), [response shapes](api/response-shapes.md), [W3Champions](concepts/w3champions.md), [ladder and achievements](concepts/ladder-and-achievements.md), [roles](concepts/roles-and-permissions.md), [deploy to Vercel](runbooks/deploy-vercel.md), [run locally](runbooks/run-locally.md) and the table concepts they name.
* **Update**: the WordPress site and the self-hosted backend are no longer consumers, and the Azure recipes are gone; a role binding defaults to the current season; with no `current_gnl_season` row the newest GNL season stands in; the W3C sync job and the bet ownership check read through a service. [Consumers](api/consumers.md), [overview](overview.md), [app-managed roles](decisions/app-managed-roles.md), [layering](conventions/layering.md), [GNL season](concepts/gnl-season.md).
* **Update**: Vercel builds only `main`. No push builds a preview, so the staging alias does not follow a merge; the `staging` branch and the staging database still do. [Overview](overview.md), [deploy to Vercel](runbooks/deploy-vercel.md), [git and pull requests](conventions/git-and-pull-requests.md).

## 2026-10-05

* **Update**: every key that points at an event cascades, except the two that set null, and so do `draft_series.match_id` and `fantasy_team_player.fantasy_team_id`, so `DELETE /events/{id}` deletes the event with every row under it and leaves the users, teams and maps it named. [event](data/tables/event.md#keys-and-joins) and the key lines of [team_season_captain](data/tables/team_season_captain.md), [round_availability](data/tables/round_availability.md), [user_season_signup](data/tables/user_season_signup.md), [map_season](data/tables/map_season.md), [event_round](data/tables/event_round.md), [team_season](data/tables/team_season.md), [user_team_season](data/tables/user_team_season.md), [draft_series](data/tables/draft_series.md) and [fantasy_team_player](data/tables/fantasy_team_player.md) state it.

## 2026-10-04

* **Update**: a player or a captain who changes a reported result through `PUT /player-series/{id}` or `/report-result`, or takes it back through `DELETE /series/{id}/result`, gets a note in the results channel beside the result card. The note names who changed it and shows the score before and after, behind spoilers, as a `discord_post` row of kind `result_change`. An admin's write, a captain's edit through `PUT /series/{id}` and a first report post none. [Series reporting](concepts/series-reporting.md#who-reports), [Discord integration](concepts/discord-integration.md#cards-and-posts) and [discord_post](data/tables/discord_post.md) state it.
* **Update**: a captain of either team of a fixture adds a series to it (`POST /series`, up to the round's series), edits one (`PUT /series/{id}`: the time, the scores, the races played, the host and the fantasy mark) and deletes one (`DELETE /series/{id}`); the seat check is the draft routes' `own_match`. `DELETE /series/{id}/result` takes a result back for whoever may report it, with its games and its result card; a walkover or a forfeit is an admin's to clear. [Series reporting](concepts/series-reporting.md#who-reports), [GNL season](concepts/gnl-season.md), [roles and permissions](concepts/roles-and-permissions.md), [Discord integration](concepts/discord-integration.md#cards-and-posts) and [response shapes](api/response-shapes.md) state it.
* **Add**: `GET /events/{event_id}/teams/summary` answers `TeamRosterSummaryPublic`, a flat roster row for the GNL website, in five statements on a finished event. [Response shapes](api/response-shapes.md#an-events-teams-list-row), [teams](data/tables/teams.md), the [edge cache](concepts/edge-cache.md) and the [consumers](api/consumers.md) state it.
* **Add**: `GET /users/{user_id}/summary` answers `UserProfileSummaryPublic`, the player page's header with the ladder summary and the tag texts, in one statement. [Response shapes](api/response-shapes.md#a-players-own-reads), [w3cstats](data/tables/w3cstats.md), the [edge cache](concepts/edge-cache.md) and the [consumers](api/consumers.md) state it.
* **Update**: `GET /me/events` and `GET /me` load only the columns their answers use, and reading any other column raises; the captain fixtures cost six statements. [The events module](concepts/events-module.md#the-member-read), [response shapes](api/response-shapes.md#loads) and [testing](conventions/testing.md) state it.
* **Update**: a finished event's reads carry a fourth timer class, finished (`s-maxage=86400`), so the edge refills each of them once a day; settled keeps its hour for a closed KOTH night, career stats and the reference lists. [Edge cache](concepts/edge-cache.md) and the [API overview](api/overview.md) state it.

## 2026-10-03

* **Add**: [koth_crown_event](data/tables/koth_crown_event.md) holds each KOTH crown change no result shows, placed after the series it followed; a fix and the played rows' crown labels walk the results and these rows in play order. [KOTH](concepts/koth.md) and [event_division](data/tables/event_division.md) state it.
* **Update**: a KOTH queue write orders only the rows it names, among the places they hold; the same winner sent again keeps a series' `result_kind`; a king whose crowned row leaves the table while he holds another row in the bracket passes the crown to it, and the series on the table comes off with no result. [KOTH](concepts/koth.md) states it.
* **Add**: `GET /home/series/upcoming` answers every booked series of a published event, at most 100, each with every claim on it, edge cached as running. [The events module](concepts/events-module.md#the-home-hub-read), [edge cache](concepts/edge-cache.md) and the [API overview](api/overview.md) state it.
* **Update**: a `GET /me/events` row carries `captain_matches`, every fixture of the caller's own team in an event the caller captains in that is not closed, in round order, so the home page leads to the team's match of any round; a captain fixture also counts its played series. [The events module](concepts/events-module.md#the-member-read) states it.

## 2026-10-02

* **Update**: a fixture's draft takes any number of pairings; `POST /draft-series` no longer refuses a full round. `POST /draft-series/{id}/promote` refuses a pairing once the fixture holds `series_per_round` published series, and the pairing stays in the draft; a replacement is free of that count. A replacement may keep one of the two players or name two new ones, so a series is replaced whole as well, and several drafts may propose a replacement of one series: publishing one removes the others with the series. [GNL season](concepts/gnl-season.md) and [draft_series](data/tables/draft_series.md) state it.

## 2026-10-01

* **Update**: the [egress monitor](api/jobs.md#the-egress-monitor) reads Vercel usage from the billing period's charges against the usage credit, lists ISR Writes, and turns amber, never red, past the credit; the Supabase daily budget is the cap spread over the cycle's days, counted on both projects.

## 2026-09-30

* **Update**: either captain of a fixture publishes its drafts (`POST /draft-series/{id}/promote`), as an admin does; the captain's fantasy mark on a draft is carried onto the series. [GNL season](concepts/gnl-season.md), [draft_series](data/tables/draft_series.md) and [roles and permissions](concepts/roles-and-permissions.md) state it.
* **Update**: the pair free-time read answers the shared intervals and each player's blocked intervals, as the series read does, sent private; the draft board says whether each player entered any availability and when he last changed it, and carries the round window. [Scheduling and availability](concepts/scheduling-and-availability.md) and [GNL season](concepts/gnl-season.md) state it.
* **Add**: [A season ends on the admin's close](decisions/season-ends-on-close.md). An event whose teams are drafted is finished by the close alone; `POST /events/{id}/finish` stamps `closed_at` on every event and `POST /events/{id}/reopen` clears it and deletes the awards; the GNL phase reads `complete` once closed and `overdue` past the end date; [GNL season](concepts/gnl-season.md), [the events module](concepts/events-module.md), [event](data/tables/event.md) and [event_award](data/tables/event_award.md) state it.
* **Update**: [what a read costs](api/overview.md#what-a-read-costs) states that a read a consumer's page calls builds each statement once, with bound parameters.

## 2026-09-29

* **Update**: the GNL payload snapshot is gone; [the events module](concepts/events-module.md) and [consumers](api/consumers.md) name `tests/test_event_season_parity.py` as the test that pins the GNL fields.

## 2026-09-28

* **Update**: [egress_ledger](data/tables/egress_ledger.md) gains `db_bytes`, the bytes each route's database connections received, measured on the socket; the [egress monitor](api/jobs.md#the-egress-monitor) sums it per day and no longer estimates bytes from rows.

## 2026-09-27

* **Add**: `GET /users/{user_id}/seasons` and `GET /users/{user_id}/series?event_id=` answer a player's seasons and GNL series from his side, computed in SQL, cached settled; [response shapes](api/response-shapes.md), [edge cache](concepts/edge-cache.md) and [consumers](api/consumers.md) state them.
* **Update**: `GET /stats/career/{user_id}` answers the row the career list holds for that user id, and 404 only when the list holds none.
* **Update**: [Response shapes](api/response-shapes.md) and [model families](data/model-families.md): every relationship of the user, team, series, draft, fantasy team, bet and season tables and of the link rows refuses an on-the-spot load (`raise_on_sql`); the embedded player summary drops `gnl_stats` and serves `record` alone.
* **Update**: [Response shapes](api/response-shapes.md) gains the fantasy rows: a fantasy team's captain and drafted players are player summaries with the record of its season; the team and the bet each answer through one read, `FantasyTeamService.get` and `FantasyBetService.get`, and `POST /fantasy-team` and `POST`, `PUT /fantasy-bet` build their answer once.
* **Update**: [Response shapes](api/response-shapes.md) gains the team and season rows: a team inside another answer is `TeamSummaryPublic` and a season `SeasonSummaryPublic`; the event team reads and writes answer `TeamRosterPublic`, one event's roster, through `roster_loads`; the league team reads and writes answer `TeamPublic`.
* **Add**: [Response shapes](api/response-shapes.md). A player inside another answer is `UserSummaryPublic`, whose `record` is the one of the read's event and whose `gnl_stats` holds that one entry; the series, draft and bet writes answer through their single read.

## 2026-09-26

* **Add**: the local dev login, `GET /dev/players` and `POST /dev/login` behind `DEV_LOGIN=1`, signs in as any player with a Discord id as a member, guest or admin, and admits only the admin token's session; the authentication page and the local runbook state it.
* **Update**: an admin who captains carries the `seats` list, so `/me` names that admin's teams and each season's `captain` flag; a view-as request drops the admin's own seats.
* **Update**: the ladder summary `race_mmrs` and `main_race` is read in SQL, one row per player and race, one statement per answer; no read loads the raw `w3cstats` rows for it.
* **Update**: `w3c_ladder_matches` gains an index on (`user_id`, `race`, `start_time`), the seek of `mmr_at`.
* **Update**: `current_w3c_season` anchors the live MMR window in the W3Champions, settings and ladder concepts; the Vercel crons, the load-all-seasons reads and the `Field(exclude=True)` pattern state the current code.
* **Update**: no user answer carries the raw `w3c_stats` rows; the ladder summary `race_mmrs` and `main_race` replaces them, and the bet and draft series reads no longer load them.
* **Update**: `PUT /koth/nights/{id}/bounds` saves while a series is on the table; the two rows of that series keep their bracket until it ends, then the cut takes them by the bounds as they stand.
* **Update**: tonight is the newest published KOTH night with no `closed_at` that started less than 24 hours ago, whatever its signup flag; `POST /koth/nights` closes an expired night first and answers 409 while another night is open; the signup doors that name no night answer "Signups are closed" while tonight's signups are off.
* **Update**: a KOTH withdraw goes through while the night is tonight, and a row that leaves forfeits: its series on the table, or as a king a new series to the first free player in line; the board's played rows carry `forfeit`.
* **Update**: `GET /events` answers `X-Total-Count`, the count of every event its filters keep, so a client pages it with `limit` and `offset`.
* **Update**: the live MMR window is the current and the previous W3Champions season; user payloads carry the ladder summary (`race_mmrs`, `main_race`), list reads load only the window's `w3cstats` rows, a roster of an event that is over carries `mmr_entered`, and the Discord series card reads the summary.
* **Add**: [Edge cache](concepts/edge-cache.md). Every cached open read uses one of three timer classes, live, running or settled; an event read is settled once the event is finished; the entrants, stage series, stage standings, achievements and an anonymous event read are cached; a player read is running.
* **Update**: a series row of a finished event carries the MMR of the time from the ladder, bounded to the event's W3Champions seasons; the MMR on a date takes a season bound; only a running event reads the current W3Champions season.
* **Update**: `monitor_state` holds a `vercel` row. With `VERCEL_USAGE_TOKEN` and `VERCEL_TEAM_ID` set, the egress monitor reads the Vercel usage over a rolling 30 days, shows it in the digest, and alerts once when a meter reaches 80% or the token is rejected.
* **Update**: `monitor_state` holds a `db_size` row. The egress monitor reads the database size on the server after each run, shows it in the digest, and alerts once when it passes 90% of the cap.
* **Add**: `monitor_state`. The egress snapshot levels the billing cycle after each run and posts Discord embeds: an alert when the cycle is on track to pass the cap or the run fails, a silent recovery when it clears, and a silent daily digest, each linking to the usage dashboards.
* **Add**: `egress_snapshot` and `egress_statement`. A daily job copies pg_stat_statements into the database and answers the rows and estimated egress since the run before, per statement, role and nesting level; `GET /jobs/egress-snapshots` lists the windows.
* **Update**: an anonymous `GET /events` carries a public cache header; an admin's bearer never reaches the edge.
* **Update**: `discordTag` and `discordId` leave every user answer but a logged-in `GET /users/{key}` and an admin's `GET /users` and `POST /users/search`, and `discord_id` leaves the cast answer; an anonymous `GET /users/{key}` carries a public cache header.

## 2026-09-25

* **Update**: the career list derives and pages in SQL; the career player read carries a public cache header.
* **Update**: the career rating uses one integer weighted sum before truncation.

## 2026-09-24

* **Add**: `link_prompt`. Only a tag Battle.net verified joins an earlier player to a login unasked; a weaker hint is a suggestion the login answers once. A claim joins at once, unverified, and a verify takes a tag another login holds unverified.
* **Update**: `users` holds no battle tag. `User.battleTag` reads the active tag row, null with none, and the workbook import finds a person with no tag by name.
* **Update**: the member signup takes a row only when no other login holds it; a tag another login holds, and a row matched only by Discord name, answer 409.
* **Update**: the users table states how a row is made: each way in, the key it looks a player up by, that a login makes no row, and the stand-in values a row with no known tag or Discord id carries.

## 2026-09-23

* **Fix**: the guild role, member or guest, is kept per process for one minute; the authentication page said nothing about membership was cached.
* **Update**: the layering convention and the model families state the measured reasons for sync handlers and for validating response models.

* **Update**: the deprecated `/seasons`, unscoped `/teams`, season-named team, series and fantasy aliases are removed; `GET /teams/{team_id}/image` stays, deprecated.
* **Update**: a helper that builds on a guard is an `Annotated` dependency, and `is_admin` in `app/core/security.py` is the one admin test.

## 2026-09-20

* **Update**: a KOTH night is paired by hand and generate refuses a `koth` stage; one signup rule holds at every door, an unrated signup stands unplaced, and the entrant seed is the line of its bracket.
* **Update**: an admin runs a KOTH night live through seven writes that each answer one board read, and the crown of a bracket is stored on `event_division.king_entrant_id`.
* **Update**: a round row of the player series read names the stage it sits in, as `stage_id` and `stage_name`.
* **Update**: the series free-time read answers each player's own blocked ranges beside the shared ones, as `blocked1` and `blocked2`.
* **Update**: the event roster read carries `out_rounds`, the rounds of the event each player sits out, on their season stats.

## 2026-09-19

* **Update**: one read answers every figure of a fixture's draft board, and a second read answers the meetings of one pairing; both carry a private cache header.
* **Update**: a fixture's draft names who wrote and who last changed each pairing, keeps a Ready mark and a seen stamp per team, counts against `series_per_round`, and publishes a pairing that replaces an open series.
* **Update**: a player checks in early where the event allows it, a round ends at midnight in the zone the event names, one write answers every round that has not ended, and a round nobody answered reads blocked out where the player's blocks cover it.
* **Update**: one rule says who acts on a series: the player a side names, a captain of the team that fields it, the roster of a side that names no player, and an admin for either side, on the player routes too.
* **Update**: a captain reads the hours two players share across a round before a series names them.
* **Update**: a replay moves to another game of its series, swapping with the replay that game holds.
* **Update**: a stage series row carries the rating of each side on the race it plays, and the team logo rides the ladder, veto board, fantasy breakdown and player history payloads.
* **Update**: the event settings for early check-in, the round end zone and the seasons the games rule counts over, and the stage setting for the largest MMR difference a captain draft pairs inside.

## 2026-09-16

* **Update**: a finished event reads `signups_open` false and refuses a signup; the withdraw takes a race; entrant counts are of players; a sized division counts its hand placements; replacing the divisions clears them off the series and matches; the payloads carry `league_name`.
* **Update**: every old `/koth/*` route is deprecated in the OpenAPI document; the live KOTH routes are the night open and close and the Twitch signup.

## 2026-09-15

* **Update**: teams belong to one league; canonical team identity routes are league-scoped, event roster and series routes are event-scoped, and the season-named forms remain deprecated aliases during migration.
* **Update**: `/events` creates and fully reads GNL runs, exposes their management subresources, and searches events; `/seasons` remains as an OpenAPI-deprecated compatibility surface.
* **Update**: KOTH states the closed stamp, one seat per player per bracket and the withdraw rule; the events module phase reads the closed stamp and keeps a scored chain running.

## 2026-09-14

* **Update**: a tag vocabulary per area, enforced by the test; `resource` and `stale_after` where they apply; the table concepts are stamped `verified` by `process:test_okf`; `# Examples` on the session answer, the error envelope, the paged list and the result report; a Start here by question guide that doubles as the benchmark; `just okf-drift`, `just okf-verify`.
* **Update**: a pass with two third-party OKF validators: the descriptions YAML misread are quoted, every concept bound to a file or a vendor carries `resource`, the runbooks carry `stale_after`, the root index carries the overview's own description, and the bundle test now checks the index lines, the tags list and unquoted values.
* **Update**: one Data Model concept per table under `data/tables/`, each listing every column with its meaning, keys and joins; `data/tables.md` becomes `data/tables/index.md`; `tests/test_okf.py` pins the columns to the concepts; the events module gains the admin's path from a new league to a finished event; the model families, GNL season and fantasy pages are corrected where they named a column the schema does not hold.
* **Update**: the events module page gains the phase rungs, the third-place rule, the previous-stage seeding guard, the drafted-teams signup rule and the check-in button rule; series reporting names the veto board's sides; the check-in hint module is renamed in scheduling and availability; KOTH names the old routes' id check.
* **Creation**: Established the bundle: conventions, concepts, data, api, runbooks, decisions and pitfalls, written from the code on `main`, the repository documents, and the maintainers' recorded decisions. Every concept is `generated` by an agent and carries no `verified` entry yet.

- 2026-09-26: Historical KOTH imports preserve unresolved identities, unavailable outcomes, source divisions and event video links.
