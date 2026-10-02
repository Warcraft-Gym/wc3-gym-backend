# Bundle history

## 2026-10-02

* **Update**: a fixture's draft takes any number of pairings; `POST /draft-series` no longer refuses a full round. `POST /draft-series/{id}/promote` refuses a pairing once the fixture holds `series_per_round` published series, and the pairing stays in the draft; a replacement is free of that count. [GNL season](concepts/gnl-season.md) and [draft_series](data/tables/draft_series.md) state it.

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
