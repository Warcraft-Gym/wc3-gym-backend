---
type: Domain Concept
title: KOTH night
description: A King of the Hill night is one event of the KOTH league with three MMR brackets as divisions, a chain per bracket paired by hand, and one signup rule at every door.
resource: ../../../app/services/koth/night.py
tags: [events, koth]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-20T18:00:00Z }
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
  - id: carry
    resource: ../../../app/services/koth/carry.py
    title: The king of each bracket of a night
---

# Shape

A night is an event of the KOTH league: one stage of format `koth`, best of one, and three divisions that are the brackets, opened at three MMR bounds. The night that takes signups is the newest published KOTH event whose signups stand open. Nothing stores "tonight". A night ends only when an admin closes it: the close deletes the series nobody played and stamps `event.closed_at`, and the stamp is what makes the night read finished. A chain with every series scored and no stamp reads running, and a closed night grows no chain.

Nothing stores a crown either. The king of a bracket is the winner of the last scored series of its chain.

Nothing draws a night: `POST /events/{id}/stages/{stage_id}/generate` refuses a `koth` stage, and a signup writes its entrant row and nothing else. The admin pairs two players of one bracket during the night. `event_entrant.seed` is the line of the bracket, 1..n in signup order: a new signup, and a withdrawn row that signs up again, take the seed after the last one of their bracket, so a late signup stands at the end and moves nobody.

# Signups

Three ways in, all through the shared entrant write under the `anyone` policy:

- the web page, `POST /events/{id}/entrants`;
- an admin, `POST /events/{id}/entrants/admin`;
- Twitch chat through Nightbot, `GET /koth/signup`, authenticated with a shared token held in settings, because Nightbot cannot send a body.

One rule holds at every door. The battle tag is the identity and must be shaped `Name#1234`, trimmed, matched without case; a tag of another shape answers 400 and writes no player. The rating comes from W3Champions alone and is never typed: when the app holds no rating for the signup race inside the rating window, the signup asks w3champions once for that tag, under a timeout short enough for a chat answer, and a tag asked about in the last hour is not asked about again. A rating found cuts the row into the bracket its MMR reaches. Nothing found, or an ask that timed out or was turned away, still takes the signup: the row stands unplaced, with no division and no place in a line, and the chat answer says an admin places the player. `PUT /events/{id}/entrants/{entrant_id}` is that placement; it marks the row placed by hand, gives it the end of its new bracket's line, and a later cut leaves it alone.

A player may enter on more than one race. Each race is its own entrant row with its own MMR and its own bracket; the unique key is (event, user, race). The page lists the player once with the races under him. Two rows of one player in one bracket both stay; the chain seats the row with the lower seed and never the second, so the draw never pairs a player with himself. A withdraw that names a race withdraws that row; one that names none withdraws every row of the player. See [the decision](../decisions/koth-multi-entry.md).

# The old payloads

`/koth/events`, `/koth/events/active`, `/koth/signups`, `/koth/matches` and `/koth/events/{id}/kings` are deprecated: the OpenAPI document marks every route of `app/api/routes/koth.py` so, and the web app calls none of them. Nightbot, the stream overlay and old bookmarks still do. `app/services/koth/legacy.py` answers those shapes from the event rows: a signup is an entrant, a match is a series of the chain, a bracket is a division, the king is derived. An old route that names an entrant or a series refuses an id that is not a KOTH entrant or series. The four old `koth_*` tables are gone; `app/models/koth_legacy.py` holds only the shapes.

The night routes are `POST /koth/nights` (open, with the start time and the three bounds), `POST /koth/nights/{id}/close`, and the event routes for everything else.
