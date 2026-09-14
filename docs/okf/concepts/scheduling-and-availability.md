---
type: Domain Concept
title: Scheduling and availability
description: A player answers whether they can play a round, keeps soft blocks that inform but never constrain, and the two players of a series see the free time they share.
tags: [scheduling, availability, rounds]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: availability
    resource: ../../../app/services/availability.py
    title: Which rounds a player cannot play
  - id: blocks
    resource: ../../../app/services/soft_blocks.py
    title: A player's own soft blocks
  - id: free-time
    resource: ../../../app/core/free_time.py
    title: Blocked and free time as UTC intervals
  - id: checkin
    resource: ../../../app/core/availability.py
    title: What the check-in shows one player for one round
---

# The unit is the round

The question "can you play?" belongs to a round, never to "every week". A round has a date window. Once a player has a series in a round the question is moot, and the series replaces the question on the dashboard. An answer is one row per player per round (`round_availability`); no row is no answer, and clearing an answer deletes the row. The player and their captain write the same row, and the last write wins. `PUT /player-availability` and `PUT /teams/{id}/seasons/{id}/availability` are the two writers, and the Discord `/availability` card is a third door to the same service.

# Ask when someone cannot play

The league ran the obvious design, a weekly poll of best times, for many seasons and dropped it: a statement of when someone cannot play is a fact, and a statement of when they are free is not. So the app asks for blocks, and blank means fully open.

What follows, each learned the hard way:

- No "preferred" state anywhere.
- No inference from ladder activity; absence of a game says nothing.
- One primitive: a time range. A standing weekly block (`user_block`) and a one-off busy date (`user_busy`) are both ranges. No categories such as work or sleep.
- A block stores local wall-clock time and an IANA zone, never a UTC mask, so daylight saving does not shift it. `app/core/free_time.py` resolves a local time the way RFC 5545 does.
- Half-hour resolution for the mask; the picker steps by the hour.
- Blocks inform, never constrain. A block never writes a round answer, never reorders a pairing and never refuses a proposed time. When a player's blocks cover a whole round window, the page shows one hint with one button to confirm.

# Free time of a series

`GET /player-series/{id}/free-time` answers the intervals both players of a series have open inside its round, from their blocks. Series times are stored in UTC, aware. See [the pitfall](../pitfalls/datetimes-are-utc.md).

# Check-in

A season may open a check-in a number of days before each round. `app/core/availability.py` computes what the check-in shows for one player and one round from their answer and their blocks; it writes nothing.
