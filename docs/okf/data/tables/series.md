---
type: Data Model
title: series
description: One series between two sides, a best-of with its scores, time, host, off races, result kind and the feeder graph a bracket runs on.
resource: ../../../../app/models/series.py
tags: [schema, events]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T15:15:00Z }
sources:
  - id: model
    resource: ../../../../app/models/series.py
    title: Series
  - id: series
    resource: ../../../../app/services/series.py
    title: SeriesService writes a GNL series
  - id: player-series
    resource: ../../../../app/services/player_series.py
    title: A player reports their own series
  - id: engine
    resource: ../../../../app/services/stage_engine.py
    title: The engine writes a generated series and follows its feeders
---

# Schema

The first block is on `SeriesBase`, which the series payloads carry. The rest stays off it, so those payloads hold; `StageSeriesRow` carries them.

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | Primary key. |
| `match_id` | INTEGER | yes | The fixture the series hangs under. Null on a generated bracket series, which stands on its own. |
| `date_time` | TIMESTAMP | yes | When the series is played, UTC. Null while unscheduled. |
| `player1_id` | INTEGER | yes | Side A's player. Null on a generated series until its feeders are scored, and on a team side. |
| `player2_id` | INTEGER | yes | Side B's player. Null the same way. |
| `player1_score` | INTEGER | yes | Maps side A won. Null means no result. |
| `player2_score` | INTEGER | yes | Maps side B won. Null means no result. |
| `host_player_id` | INTEGER | no | The player who hosts the games. 0 when no side is named yet. No foreign key. |
| `is_fantasy_match` | BOOLEAN | yes | On: the series counts for the fantasy game. The `/upcoming` command filters on it. Null means unmarked. |
| `player1_off_race` | VARCHAR | yes | The race side A played when it was not the signup race. Null means the signup race. |
| `player2_off_race` | VARCHAR | yes | The same for side B. |
| `entrant1_id` | INTEGER | yes | The entrant on side A. A solo entrant also fills `player1_id`; a team entrant leaves it null and its roster plays the side. Only the engine writes it. |
| `entrant2_id` | INTEGER | yes | The entrant on side B. |
| `round_id` | INTEGER | yes | The round the series is played in. Resolved on flush for a GNL series. |
| `sequence` | INTEGER | yes | The place of the series inside its round, its fixture or its chain. |
| `side_size` | INTEGER | no | Players per side: 1 for a 1v1, 2 for a 2v2. |
| `pick_rule` | VARCHAR | yes | How the sides of a fixture series are chosen: `drafted` by the captains, or `any`. Null on a series outside a template. |
| `result_kind` | VARCHAR | no | `played`, `walkover` or `forfeit`. |
| `slot1_from_series_id` | INTEGER | yes | The series that feeds side A. Null when side A is seeded directly. |
| `slot1_takes_loser` | BOOLEAN | no | On: side A takes the loser of that series, as a lower bracket does. |
| `slot2_from_series_id` | INTEGER | yes | The series that feeds side B. |
| `slot2_takes_loser` | BOOLEAN | no | On: side B takes the loser. |
| `division_id` | INTEGER | yes | The division the series is played in. Null while the event has one table. |

# Keys and joins

Primary key `id`. Foreign keys: `match_id` to [matches](matches.md), cascade; `player1_id` and `player2_id` to [users](users.md), cascade; `entrant1_id` and `entrant2_id` to [event_entrant](event_entrant.md), set null; `round_id` to [event_round](event_round.md), cascade; `slot1_from_series_id` and `slot2_from_series_id` to [series](series.md), set null; `division_id` to [event_division](event_division.md), set null. Unique index on (`match_id`, `player1_id`, `player2_id`).

Pointed at by [series_side](series_side.md), [series_game](series_game.md), [series_replay](series_replay.md), [series_veto_step](series_veto_step.md), [series_cast](series_cast.md) and [fantasy_bets](fantasy_bets.md).

# Rules

- Points, the resolved race per side and the rules the series plays under derive on every read. See [derived scores](../../concepts/derived-scores.md) and [series reporting](../../concepts/series-reporting.md).
- A series that names an entrant was generated and prices on its stage; a GNL series names two players and a fixture. See [the off-race decision](../../decisions/off-race-per-series.md).
- A series with no result has both scores null; a result sets both. The games behind the score are [series_game](series_game.md) rows.
