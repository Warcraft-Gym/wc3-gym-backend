---
type: Domain Concept
title: KOTH night
description: A King of the Hill night is one event of the KOTH league with three MMR brackets as divisions, one signup rule at every door, and every series paired by hand while the night runs.
resource: ../../../app/services/koth/night.py
tags: [events, koth]
generated: { by: claude-code/claude-opus-5-5, at: 2026-09-26T04:00:00Z }
sources:
  - id: night
    resource: ../../../app/services/koth/night.py
    title: Open and close a night
  - id: nightbot
    resource: ../../../app/services/koth/nightbot.py
    title: The Twitch signup
  - id: legacy
    resource: ../../../app/services/koth/legacy.py
    title: The old /koth/* payloads answered from the event model
  - id: signup
    resource: ../../../app/services/koth/signup.py
    title: The one signup rule of a night
  - id: live
    resource: ../../../app/services/koth/live.py
    title: The live night an admin runs by hand
  - id: board
    resource: ../../../app/services/koth/board.py
    title: The one board read
  - id: carry
    resource: ../../../app/services/koth/carry.py
    title: The king of each bracket of a night
---

# Shape

A night is an event of the KOTH league: one stage of format `koth`, best of one, and three divisions that are the brackets, opened at three MMR bounds. The night that takes signups is the newest published KOTH event whose signups stand open. Nothing stores "tonight". A night ends only when an admin closes it: the close deletes the series nobody played and stamps `event.closed_at`, and the stamp is what makes the night read finished. A chain with every series scored and no stamp reads running, and a closed night grows no chain.

A bracket holds one king, and the crown is stored on the bracket row as `event_division.king_entrant_id`. An empty throne is taken by the winner of the next series the bracket plays; after that the crown moves only in a series the reigning king played and lost, so a side game between two other rows leaves it where it stands. Turning a result around moves the crown back, because the king the old result crowned is one of the two sides. Only a save that changes who won moves the crown, so saving another field of a series, or sending the same result again, leaves it where it stands. Two admin writes move it without a game: pass it to another row of the same bracket, or empty the throne. A row that leaves the night, and a row an admin moves to another bracket, leaves the throne empty and does not take the crown back on return. A `koth` stage that runs no divisions has no row to store a crown on, so its throne reads as the winner of the last series it scored.

Nothing draws a night: `POST /events/{id}/stages/{stage_id}/generate` refuses a `koth` stage, and a signup writes its entrant row and nothing else. The admin pairs two players of one bracket during the night. `event_entrant.seed` is the line of the bracket, rising in signup order: a new signup, and a withdrawn row that signs up again, take the seed after the last one of their bracket, so a late signup stands at the end and moves nobody. A bracket a row left keeps the gap its seed leaves, so the line is read in seed order and not by its numbers.

# Signups

Three ways in, all through the shared entrant write under the `anyone` policy:

- the web page, `POST /events/{id}/entrants`;
- an admin, `POST /events/{id}/entrants/admin`;
- Twitch chat through Nightbot, `GET /koth/signup`, authenticated with a shared token held in settings, because Nightbot cannot send a body.

One rule holds at every door. The battle tag is the identity and must be shaped `Name#1234`, trimmed, matched without case against every tag a person holds, so a member's second tag enters that member; a tag of another shape answers 400 and writes no player. A new tag writes a person with that tag as the active one. The rating comes from W3Champions alone and is never typed: when the app holds no rating for the signup race inside the rating window, the signup asks w3champions once for that tag, under a timeout short enough for a chat answer, and a tag asked about in the last hour is not asked about again. A rating found cuts the row into the bracket its MMR reaches. Nothing found, or an ask that timed out or was turned away, still takes the signup: the row stands unplaced, with no division and no place in a line, and the chat answer says an admin places the player. `PUT /events/{id}/entrants/{entrant_id}` is that placement; it marks the row placed by hand, gives it the end of its new bracket's line, and a later cut leaves it alone. A rating that arrives after the signup is read by the next cut: the row it moves into a bracket takes the end of that bracket's line, a row the cut leaves where it stands keeps its place, and a player who withdraws and signs up again takes the end again.

A player may enter on more than one race. Each race is its own entrant row with its own MMR and its own bracket; the unique key is (event, user, race). The page lists the player once with the races under him. Two rows of one player in one bracket both stay; a player a series of the chain already names takes no second seat in it. A withdraw that names a race withdraws that row; one that names none withdraws every row of the player. See [the decision](../decisions/koth-multi-entry.md).

# The old payloads

`/koth/events`, `/koth/events/active`, `/koth/signups`, `/koth/matches` and `/koth/events/{id}/kings` are deprecated: the OpenAPI document marks every route of `app/api/routes/koth.py` so, and the web app calls none of them. Nightbot, the stream overlay and old bookmarks still do. `app/services/koth/legacy.py` answers those shapes from the event rows: a signup is an entrant, a match is a series of the chain that names both entrant rows, a bracket is a division, the king is the stored crown of the division. An old route that names an entrant or a series refuses an id that is not a KOTH entrant or series. The four old `koth_*` tables are gone; `app/models/koth_legacy.py` holds only the shapes.

# Running the night

An admin makes every series by hand while the night runs. `POST /koth/nights/{id}/series` names two entrant rows of one bracket and writes one best of one series with no date and no feeder. It refuses two rows of one player, rows of two brackets, a row that left and a closed night, and it answers 409 while that bracket already holds a series with no result. `DELETE /koth/nights/{id}/series/{series_id}` takes an unplayed series off the table. `PUT /koth/nights/{id}/series/{series_id}/result` names the winning side, writes the 1-0 every other reader of a series expects, and turns a result of the night around when it is called again. The beaten player goes to the end of his bracket's line and the winner leaves it while he is king.

The line is `event_entrant.seed` inside the bracket, first in line first, one place per player whatever races he holds there. `PUT /koth/nights/{id}/brackets/{division_id}/queue` writes the order of one bracket and touches no other. `PUT /koth/nights/{id}/brackets/{division_id}/crown` passes the crown or empties the throne. `DELETE /koth/nights/{id}/entrants/{entrant_id}` takes a row out of the night, off the throne and off the table; `POST /koth/nights/{id}/entrants/{entrant_id}/restore` puts it back at the end of the line. Every one of these writes takes an admin and answers the board.

`PUT /koth/nights/{id}/bounds` moves the MMR bounds of the brackets while the night runs. The body names every bracket of the night exactly once with its new `lower_bound`; the bounds keep the order of the brackets, no two are equal, and the weakest bracket opens at 0. A body that breaks one of those rules, or a closed night, answers 400, and the route answers 409 while any bracket of the night holds a series with no result. The bracket rows are written in place, so their ids, their names, their order, the crowns and every series keep their rows; only the bound changes. The night is then cut again by the new bounds, exactly as a signup cuts it: a row an admin placed by hand and a row no bound reaches stay where they are, a row the cut moves takes the end of its new bracket's line, and a king whose row moves leaves the throne he wore empty.

# The board

`GET /koth/nights/{id}/board`, and `GET /koth/board` for the night that takes signups, is the one read the run page and the public dashboard both draw. It takes no token and carries `Cache-Control: public, s-maxage=15` and `Access-Control-Allow-Origin: *`, because the dashboard polls it while the night runs. A night that is not published is an admin's own, so the public read answers not found. It answers the night and its counts, the rows no bracket holds yet, and per bracket its name and bound, the king with the race rows he holds there, the king of the last closed night while the throne is still empty, the series on the table, the line in order with one item per player and a mark on a player who plays in another bracket, the rows that left, and the series played, newest first, each saying whether the throne moved, was held, or never applied. A player on the table holds no seat in the line, whatever other race rows he has there. Every player line carries one rating integer and no W3Champions stats: the read asks for the rating of each (player, race) pair and four columns of each player, never a stored stats row. Thirty rows and one played series read 3989 bytes over ten statements, none of them per row.

The shape it answers, as `app/models/koth_night.py` states it:

- `KothBoard`: `night_id`, `name`, `starts_at`, `closed`, `entrant_count`, `series_count`, `unplaced` (`KothPlayer` list), `brackets` (`KothBracket` list). The header names the event by `night_id`, and a night that is over reads `closed` true; there is no state word.
- `KothBracket`: `division_id`, `name`, `lower_bound`, `king` (`KothSeat` or null), `defender` (`KothPlayer` or null, and only while the throne is empty), `open_series` (`KothOpenSeries` or null), `queue` (`KothSeat` list), `left` (`KothPlayer` list), `played` (`KothPlayed` list, newest first).
- `KothSeat`: `user_id`, `name`, `country`, `rows` (`KothRow` list), `busy`. One seat is one player, whatever races he holds in that bracket.
- `KothRow`: `entrant_id`, `race`, `mmr`.
- `KothPlayer`: `entrant_id`, `user_id`, `name`, `country`, `race`, `mmr`. One race row, not a seat.
- `KothOpenSeries`: `series_id`, `side1`, `side2`, both `KothPlayer`.
- `KothPlayed`: `series_id`, `winner`, `loser`, `winner_side` (1 or 2), `throne` (`moved`, `held` or `none`), `replay`. `winner_side` is the side of the series the winner played, so a client turns a result around with the other side and reads no series.

`mmr` null on a race row of a bracket says W3Champions found no rating for that player on that race; no second field carries that. Every row of `unplaced` reads `mmr` null, because a row no bracket holds is not asked for a rating.

The night routes are `POST /koth/nights` (open, with the start time and the three bounds), `POST /koth/nights/{id}/close`, and the event routes for everything else. The close deletes the series on every bracket's table and leaves the crowns readable, so the next night can name each bracket's defender.

# Historical imports

An offline capture imports into real events, source divisions, entrants, ordered BO1 series and one game per series. The importer verifies capture checksums, validates the whole batch, and commits each event atomically. Source keys and digests make reruns idempotent and refuse changed evidence. A target with unmapped KOTH events requires reconciliation before import.

Source names identify archival participants within one event and section. No shorthand creates an account or implies a race. Missing dates, maps, winners and award instants remain null. Random games and placeholders stay in private source evidence and create no competitive series. Reported crowns do not imply BO1 winners.

The historical board returns `historical`, `date_label` and event `videos`. Each bracket retains its literal name and explicit numeric bounds, `historical_king`, and ordered `history` rows with two sides and a nullable winner. Categorical and approximate labels remain authoritative; neighbouring divisions never define a missing bound. No historical board reads ladder ratings or opens a queue. Live latest-night and defender reads exclude imported history.

The board retains its fifteen-second edge cache. Imported events are limited to five hundred series, twenty divisions and one hundred videos; larger inputs require a paged reader. The board selects source labels and never returns raw source records. Event series reads retain their page limit and include standalone series through rounds.

The import command requires an explicit loopback PostgreSQL URL, defaults to dry-run, and reads only offline files. Account claims, race corrections and reviewed source reconciliation are separate workflows.
