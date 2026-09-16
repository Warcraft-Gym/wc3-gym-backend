---
type: Domain Concept
title: Derived scores
description: Series points, fixture scores, standings, career ratings and fantasy scores are computed from the map scores on every read, in a constant number of statements.
resource: ../../../app/services/derived.py
tags: [events, series, api]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: derived
    resource: ../../../app/services/derived.py
    title: The read-time derivation
  - id: scoring
    resource: ../../../app/core/scoring.py
    title: The series scoring rule, Python and SQL
  - id: career
    resource: ../../../app/core/career.py
    title: The career rating rule
  - id: budget
    resource: ../../../tests/test_query_budget.py
    title: The statement budget
---

# The rule

A series stores only the maps each side won. Everything else is computed when it is read:

- **Series points.** A lost series keeps its map score. A won series pays the top of the scale minus the loser's maps. The scale comes from the season's `score_system` and the maps a win takes: `standard` tops at 2*wins-1, `helpstone` at 2*wins. A Bo3 tops at 3 or 4.
- **Fixture score.** The sum of the series points per side.
- **Standings.** The sum over a team's fixtures. A team with no played series reads (0, 0, full points available); there is no null state.
- **Career rating.** A season pays a player one point per series won, half a point per other series played, and one point for playing at all. Every league season first takes 15% off the rating a player carries. The fold runs over the seasons in order, so it depends on the whole league.
- **Fantasy scores.** See [fantasy](fantasy.md).
- **Per-player season record.** Games, wins and losses per season, from the series.

# Why helpstone exists

Under the old 3/2/1/0 scale a 2:1 was undervalued and a 1:2 overvalued, so three Bo3 wins could tie one. Helpstone pays 4 per Bo3: both sides start at 2, each map is +1 to the winner and -1 to the loser.

# Two faces, one rule

Each rule has a Python face for loaded rows and a SQL `CASE` face for aggregates, both in `app/core/`. A test pins the two to each other over every combination. `app/services/derived.py` fills a response in two statements: one resolves the scale of every series or season in it, one sums the series on that scale. Seasons that share a scale share a statement. `tests/test_query_budget.py` fails when a serialization adds a lazy load.

# What must never come back

No stored `points`, `team_score`, `final_score`, `rating` or fantasy total column. No recalculate route or button. Stored rollups caused a wipe bug, write races, a recalculation button people forgot to press, and import staleness. A new derived value goes in `derived.py` with a constant-statement fill and a budget test, with its pure rule in `app/core/`. See [the decision](../decisions/derived-not-stored.md).

# Ladder and achievements

The W3Champions ladder points and the 24 achievement badges follow the same pattern: matches are stored, points and badges derive. See [ladder and achievements](ladder-and-achievements.md).
