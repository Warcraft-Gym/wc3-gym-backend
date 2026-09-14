---
type: Pitfall
title: A replay does not give up the winner
description: A .w3g yields the map and the battle tags from its first block; the winner is not readable, and a hand-written record walker was rejected.
tags: [pitfall, replays]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: source
    resource: ../../../app/services/replays.py
    title: The replay slots
---

# What happened

A record-by-record walk over the replay's game events was written to guess a winner from who left first. It was a hand-written parser over a format the app does not own, unverifiable on one sample and fragile on every client version. It was cut back.

# The rule

Read the header and the first inflated block: the map path and both battle tags. Match a map by its human name, because W3Champions renames the file per game. Never walk records without approval. In a 1v1 the loser usually leaves first; that is a warning, never a verdict.
