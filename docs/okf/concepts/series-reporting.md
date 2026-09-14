---
type: Domain Concept
title: Series reporting
description: A result is reported game by game with a map and a replay per game, a veto board that is derived from the season rules, an off race per side, and casts that any member may claim.
resource: ../../../app/services/series_games.py
tags: [series, veto, replays, casts]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T14:30:00Z }
sources:
  - id: games
    resource: ../../../app/services/series_games.py
    title: The games of a series
  - id: veto
    resource: ../../../app/services/series_veto.py
    title: The map veto, step by step
  - id: map-order
    resource: ../../../app/core/map_order.py
    title: Which map each game is played on
  - id: replays
    resource: ../../../app/services/replays.py
    title: One replay file per game
  - id: casts
    resource: ../../../app/services/casts.py
    title: Who streams a series
  - id: player-series
    resource: ../../../app/services/player_series.py
    title: A player's own series
---

# Who reports

A player on either side of a series, or an admin, writes the result through `PUT /player-series/{id}`; the Discord `/score` command goes through the same write. The two series scores stay the total; `series_game` rows say how the total was reached, one per game with the side that won and the map. A third of GNL series go to a deciding game, so the per-game winner cannot be derived from the score and is stored.

A series that was not played takes `result_kind` `walkover` or `forfeit` with a winner, through `PUT /series/{id}/result-kind`, admin only.

# Maps

The season's `map_rules` names one rule per game: `fixed` takes the round's map (`event_round.map_id`), `loser` takes the map the loser of the game before picked, `host` and `veto` leave the game to the report. The GNL default when `map_rules` is null is `fixed,loser,loser`. What a game was played on is what the report stored; the rule only says what to offer when nothing is stored yet. The board answer still carries a field named `week_map_id`; renaming it needs both repositories to deploy in step, so it stays.

# The veto board

The board is derived: the season's `pick_ban` names the order and the side of every step, the season's pool names the maps, and a `fixed` rule takes its map off the board because it is already game 1. Only the steps taken are stored (`series_veto_step`, with `entered_by`). A veto done elsewhere is entered after the fact on the same board. The board is the one place a veto exists; there is no launcher, no ad-hoc lobby, and the Discord `/veto` command only points at the board.

The veto is not a required input. The report warns, strongly, when a result comes without one; it never blocks. See [the decision](../decisions/veto-warns-never-blocks.md).

Each side of the board answer is a player or a team: `id` and `name` are the user's, null for a team side, which carries `team_id` and `team_name` instead. `viewer_side` names the side the caller acts for, null for an admin, who edits either side.

# Off race

A player who played another race than their signup race in one series records it on that series: `player1_off_race` / `player2_off_race`, nullable, null meaning the signup race. The resolved race, `player1_race` / `player2_race` on the response, is filled at read time and is on no write model. The two names are deliberate: an admin edit and the Discord command re-send the whole object, and one shared name would pin the resolved race into the column. Store null when the submitted race equals the signup race. See [the decision](../decisions/off-race-per-series.md).

# Replays

Replays live in a Cloudflare R2 bucket, one file per game. The browser uploads straight to the bucket on a presigned URL from `POST /player-series/{id}/replays/{game}/upload-url`, so no file passes through a Vercel function. A slot row is written only once the file is there, starts like a replay and is under the size cap. Keys start with the deployment environment, so two builds never share a file. A deleted series drops its files after the commit. The S18 replays from before the app are not recovered, by decision.

# Casts

Any member claims a series once (`POST /series/{id}/casts`); the owner or an admin changes the channel or removes it, and sets the VOD. A series with a result is over and takes no claim. The claim posts a card in Discord, and a reminder card goes out shortly before the start through `GET /jobs/cast-reminders`. See [Discord integration](discord-integration.md).
