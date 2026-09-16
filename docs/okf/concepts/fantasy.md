---
type: Domain Concept
title: Fantasy league
description: A member drafts players, one team and one race for a season, places bets on series, and scores six derived parts.
resource: ../../../app/core/fantasy.py
tags: [fantasy]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T15:15:00Z }
sources:
  - id: rule
    resource: ../../../app/core/fantasy.py
    title: The fantasy scoring rule
  - id: teams
    resource: ../../../app/services/fantasy_teams.py
    title: FantasyTeamService
  - id: bets
    resource: ../../../app/services/fantasy_bets.py
    title: FantasyBetService
  - id: breakdown
    resource: ../../../app/services/fantasy_scores.py
    title: The per-team score breakdown
---

# Shape

A fantasy team belongs to one member, the Fantasy Captain, and one season. It drafts players, one real team, one race, and, when the season offers it, a grind pick (a second team paid by achievement rank). The captain places bets: a stake of points on one series and a call. A member creates a team while the season is `open`; creation locks when it commences.

Players are grouped into fantasy tiers by MMR. The season stores the ascending MMR cuts in `fantasy_tier_cuts` and the apply date in `fantasy_tiers_applied_at`; an allocation writes each signup's `fantasy_tier`, and a signup with none derives its tier from the MMR on that date. `fantasy_tier_pinned` on the answer is derived, never stored.

# Scoring, all derived at read time

| Part | Pays |
|---|---|
| drafted players | the points of every series they played that season, plus 5 bench points for a week with no series |
| drafted team | its standing in the season |
| drafted race | the weekly race table: wins over losses; the three best ratios of a week take 18, 12, 6; ties share a rank |
| bets | the stake, added when the call was right and subtracted when it was wrong |
| grind pick | with N teams the rank r pays N - r + 1 |
| total | the sum |

`app/core/fantasy.py` holds the rule and reads no database. `app/services/derived.py` fills the list answer in a constant number of statements; `fantasy_scores.py` builds the same numbers for one team with the breakdown the page shows. A bet result costs no statement, because the series scores already ride in the response. No column stores a fantasy total, and there is no recalculate route. See [derived scores](derived-scores.md).

# Routes

Admin routes under `/fantasy/...` manage teams, bets and tiers. Member routes `POST /fantasy-team`, `POST /fantasy-bet`, `PUT /fantasy-bet/{id}`, `DELETE /fantasy-bet/{id}` are ownership-checked. `GET /fantasy/teams/{id}/season/{id}/breakdown` answers the per-part breakdown. The leaderboard is read by the site and the Discord `/leaderboard` command. Workbooks import fantasy teams and bets in one transaction each.

# Words

The person is a "Fantasy Captain" in every user-facing string. The API field stays `captain_id` with the value `captain`. A Fantasy Captain is not a GNL team captain and holds no seat. See [roles](roles-and-permissions.md).
