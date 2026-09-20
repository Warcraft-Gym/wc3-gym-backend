---
type: Domain Concept
title: KOTH night
description: A King of the Hill night is one event of the KOTH league with three MMR brackets as divisions, a chain per bracket, and a Twitch chat signup.
resource: ../../../app/services/koth/night.py
tags: [events, koth]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-20T12:00:00Z }
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
  - id: live
    resource: ../../../app/services/koth/live.py
    title: The live night an admin runs by hand
  - id: board
    resource: ../../../app/services/koth/board.py
    title: The one board read
  - id: carry
    resource: ../../../app/services/koth/carry.py
    title: Carry the king of the last event
---

# Shape

A night is an event of the KOTH league: one stage of format `koth`, best of one, and three divisions that are the brackets, opened at three MMR bounds. The night that takes signups is the newest published KOTH event whose signups stand open. Nothing stores "tonight". A night ends only when an admin closes it: the close deletes the series nobody played and stamps `event.closed_at`, and the stamp is what makes the night read finished. A chain with every series scored and no stamp reads running, and a closed night grows no chain.

A bracket holds one king, and the crown is stored on the bracket row as `event_division.king_entrant_id`. An empty throne is taken by the winner of the next series the bracket plays; after that the crown moves only in a series the reigning king played and lost, so a side game between two other rows leaves it where it stands. Turning a result around moves the crown back, because the king the old result crowned is one of the two sides. Two admin writes move it without a game: pass it to another row of the same bracket, or empty the throne. A row that leaves the night loses the crown and does not take it back when it returns. A `koth` stage that runs no divisions has no row to store a crown on, so its throne reads as the winner of the last series it scored.

Opening a new night carries the king of the last event first in the seed order; the rest follow on MMR.

# Signups

Three ways in, all through the shared entrant write under the `anyone` policy:

- the web page, `POST /events/{id}/entrants`;
- an admin, `POST /events/{id}/entrants/admin`;
- Twitch chat through Nightbot, `GET /koth/signup`, authenticated with a shared token held in settings, because Nightbot cannot send a body.

A player may enter on more than one race. Each race is its own entrant row with its own MMR and its own bracket; the unique key is (event, user, race). The page lists the player once with the races under him. Two rows of one player in one bracket both stay; the chain seats the row with the lower seed and never the second, so the draw never pairs a player with himself. A withdraw that names a race withdraws that row; one that names none withdraws every row of the player. See [the decision](../decisions/koth-multi-entry.md).

# The old payloads

`/koth/events`, `/koth/events/active`, `/koth/signups`, `/koth/matches` and `/koth/events/{id}/kings` are deprecated: the OpenAPI document marks every route of `app/api/routes/koth.py` so, and the web app calls none of them. Nightbot, the stream overlay and old bookmarks still do. `app/services/koth/legacy.py` answers those shapes from the event rows: a signup is an entrant, a match is a series of the chain, a bracket is a division, the king is derived. An old route that names an entrant or a series refuses an id that is not a KOTH entrant or series. The four old `koth_*` tables are gone; `app/models/koth_legacy.py` holds only the shapes.

# Running the night

An admin makes every series by hand while the night runs. `POST /koth/nights/{id}/series` names two entrant rows of one bracket and writes one best of one series with no date and no feeder. It refuses two rows of one player, rows of two brackets, a row that left and a closed night, and it answers 409 while that bracket already holds a series with no result. `DELETE /koth/nights/{id}/series/{series_id}` takes an unplayed series off the table. `PUT /koth/nights/{id}/series/{series_id}/result` names the winning side, writes the 1-0 every other reader of a series expects, and turns a result of the night around when it is called again. The beaten player goes to the end of his bracket's line and the winner leaves it while he is king.

The line is `event_entrant.seed` inside the bracket, first in line first, one place per player whatever races he holds there. `PUT /koth/nights/{id}/brackets/{division_id}/queue` writes the order of one bracket and touches no other. `PUT /koth/nights/{id}/brackets/{division_id}/crown` passes the crown or empties the throne. `DELETE /koth/nights/{id}/entrants/{entrant_id}` takes a row out of the night, off the throne and off the table; `POST /koth/nights/{id}/entrants/{entrant_id}/restore` puts it back at the end of the line. Every one of these writes takes an admin and answers the board.

# The board

`GET /koth/nights/{id}/board`, and `GET /koth/board` for the night that takes signups, is the one read the run page and the public dashboard both draw. It takes no token and carries `Cache-Control: public, s-maxage=15` and `Access-Control-Allow-Origin: *`, because the dashboard polls it while the night runs. It answers the night and its counts, the rows no bracket holds yet, and per bracket its name and bound, the king with the race rows he holds there, the king of the last closed night while the throne is still empty, the series on the table, the line in order with one item per player and a mark on a player who plays in another bracket, the rows that left, and the series played, newest first, each saying whether the throne moved, was held, or never applied. Every player line carries one rating integer and no W3Champions stats. The read costs a fixed number of statements, none of them per row.

The night routes are `POST /koth/nights` (open, with the start time and the three bounds), `POST /koth/nights/{id}/close`, and the event routes for everything else. The close deletes the series on every bracket's table and leaves the crowns readable, so the next night can name each bracket's defender.
