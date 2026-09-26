# Bundle history

## 2026-09-26

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
