---
type: Domain Concept
title: KOTH night
description: A King of the Hill night is one event of the KOTH league with three MMR brackets as divisions, a chain per bracket, and a Twitch chat signup.
resource: ../../../app/services/koth/night.py
tags: [koth, events, domain]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-15T09:00:00Z }
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
  - id: carry
    resource: ../../../app/services/koth/carry.py
    title: Carry last night's king
---

# Shape

A night is an event of the KOTH league: one stage of format `koth`, best of one, and three divisions that are the brackets, opened at three MMR bounds. The night that takes signups is the newest published KOTH event whose signups stand open. Nothing stores "tonight". A night ends only when an admin closes it: the close deletes the series nobody played and stamps `event.closed_at`, and the stamp is what makes the night read finished. A chain with every series scored and no stamp reads running, and a closed night grows no chain.

Nothing stores a crown either. The king of a bracket is the winner of the last scored series of its chain. Opening a new night carries last night's king first in the seed order; the rest follow on MMR.

# Signups

Three ways in, all through the shared entrant write under the `anyone` policy:

- the web page, `POST /events/{id}/entrants`;
- an admin, `POST /events/{id}/entrants/admin`;
- Twitch chat through Nightbot, `GET /koth/signup`, authenticated with a shared token held in settings, because Nightbot cannot send a body.

A player may enter on more than one race. Each race is its own entrant row with its own MMR and its own bracket; the unique key is (event, user, race). The page lists the player once with the races under him. Two rows of one player in one bracket both stay; the chain seats the row with the lower seed and never the second, so the draw never pairs a player with himself. A withdraw that names a race withdraws that row; one that names none withdraws every row of the player. See [the decision](../decisions/koth-multi-entry.md).

# The old payloads

Nightbot, the stream overlay and the run crew's bookmarks still call `/koth/events`, `/koth/events/active`, `/koth/signups`, `/koth/matches` and `/koth/events/{id}/kings`. `app/services/koth/legacy.py` answers those shapes from the event rows: a signup is an entrant, a match is a series of the chain, a bracket is a division, the king is derived. An old route that names an entrant or a series refuses an id that is not a KOTH entrant or series. The four old `koth_*` tables are gone; `app/models/koth_legacy.py` holds only the shapes.

The night routes are `POST /koth/nights` (open, with the start time and the three bounds), `POST /koth/nights/{id}/close`, and the event routes for everything else.
