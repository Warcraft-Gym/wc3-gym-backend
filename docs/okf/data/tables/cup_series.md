---
type: Data Model
title: cup_series
description: One series a cup plays, drawn by the cup engine into a round of a stage, with its two sides, its result and the feeders it takes its sides from.
resource: ../../../../app/models/cup_series.py
tags: [events, series, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-14T18:00:00Z }
sources:
  - id: model
    resource: ../../../../app/models/cup_series.py
    title: CupSeries
  - id: engine
    resource: ../../../../app/services/cup_engine.py
    title: the draw, the feeders and the tables
  - id: service
    resource: ../../../../app/services/cup_series.py
    title: report, score, clear and award
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | Primary key. |
| `round_id` | INTEGER | no | The round of the stage the series is drawn in. |
| `division_id` | INTEGER | yes | The division whose bracket or table the series belongs to. |
| `sequence` | INTEGER | yes | Where the series sits in its round, from 1. |
| `lobby_map_id` | INTEGER | yes | The map a free for all lobby is played on, drawn from the cup's pool when the lobby is drawn, the lobbies of one round on different maps while the pool holds enough; a runner changes it with `PUT /cup-series/{id}/lobby-map` until the lobby has its result. Null on a two-sided series, which names its maps per game. |
| `entrant1_id` | INTEGER | yes | The entrant on side A. Null while a feeder has not sent it. |
| `entrant2_id` | INTEGER | yes | The entrant on side B. Null for a bye and while a feeder has not sent it. |
| `player1_id` | INTEGER | yes | The player of side A when the entrant is a player. Null for a team side and a lobby. |
| `player2_id` | INTEGER | yes | The player of side B when the entrant is a player. Null for a team side and a lobby. |
| `player1_score` | INTEGER | yes | The maps side A won. Null until a result. |
| `player2_score` | INTEGER | yes | The maps side B won. Null until a result. |
| `result_kind` | VARCHAR(10) | no | `played`, `walkover` or `forfeit`. Defaults to `played`. |
| `player1_off_race` | race | yes | The race side A played when it is not the race it entered on. |
| `player2_off_race` | race | yes | The race side B played when it is not the race it entered on. |
| `side_size` | INTEGER | no | How many players a side holds: 1 for a 1v1. Defaults to 1. |
| `slot1_from_series_id` | INTEGER | yes | The series side A comes from. Null when it is seeded. |
| `slot1_takes_loser` | BOOLEAN | no | Whether side A takes the loser of its feeder. Defaults to false. |
| `slot2_from_series_id` | INTEGER | yes | The series side B comes from. Null when it is seeded. |
| `slot2_takes_loser` | BOOLEAN | no | Whether side B takes the loser of its feeder. Defaults to false. |

# Keys and joins

Primary key `id`. Foreign keys: `round_id` to [event_round](event_round.md), cascade; `division_id` to [event_division](event_division.md), set null; `entrant1_id` and `entrant2_id` to [event_entrant](event_entrant.md), set null; `player1_id` and `player2_id` to [users](users.md), cascade; `slot1_from_series_id` and `slot2_from_series_id` to this table, set null. `lobby_map_id` to [maps](maps.md), set null. Indexed on `round_id`, both entrants and both players. Its games are [cup_series_game](cup_series_game.md) rows, its veto [cup_veto_step](cup_veto_step.md) rows and its lobby seats [cup_series_side](cup_series_side.md) rows; each cascades with the series.

# Rules

- Only a cup writes here, and a cup writes nowhere else: GNL and KOTH keep [series](series.md). See [cups keep their own tables](../../decisions/cups-own-tables.md).
- A result is both scores or neither, and finishes the series at the wins its best-of takes, or reads 0-0 for a series never played. A cleared result takes its games along and reads `played` again.
- A result fills every slot that feeds from the series and settles a bye or a forfeit below it; clearing it takes those sides back. See [events module](../../concepts/events-module.md#cup-series).
- The payload `CupSeriesPublic` answers the same field names a stage series box reads, without a fixture, a host, a cast or a replay.
