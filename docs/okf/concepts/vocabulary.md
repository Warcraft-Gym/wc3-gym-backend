---
type: Domain Concept
title: Vocabulary
description: One word per thing, from league down to game, and the words this app keeps for old reasons.
resource: ../../../app/models/enums.py
tags: [events]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: enums
    resource: ../../../app/models/enums.py
    title: The enumerations that store these words
  - id: decision
    resource: Maintainers' decision, 2026-09-13
    title: Events module words
---

# The ladder of things

League > event > stage > round > fixture > series > game.

| Word | Meaning | Table |
|---|---|---|
| League | What repeats: Gym Newbie League (GNL), Gym KOTH, a community league. Holds defaults and history. `kind` is `gnl`, `koth` or `custom`. | `league` |
| Event | One run of a league that people sign up for: a GNL season, a KOTH night, a cup, a sign-up list. `kind` is `gnl`, `cup`, `koth` or `signup`. | `event` (the class is still named `Season`) |
| Stage | One format played over the entrants: `round_robin`, `gnl`, `single_elimination`, `double_elimination`, `swiss`, `koth`, `ffa`. Stages play in order; the next takes the top N of the last. | `event_stage` |
| Round | One ordered group of series inside a stage, with an optional date window. A GNL week is a round. | `event_round` |
| Fixture | The pairing of two team entrants in a round. It holds series. A GNL week has one fixture per team pairing. | `matches` |
| Series | One opponent per side and a best-of. A 2v2 Bo3 is one series with sides of two. Schedule, casts, bets, veto and reports attach here. | `series` |
| Game | One map inside a series, with a winner. | `series_game` |
| Division | A band of entrants that runs the whole event in parallel and never merges: KOTH's brackets, a beginner and a pro bracket. | `event_division` |
| Group | A stage partition that merges at the next stage. | `event_entrant.group_no` |
| Qualifier | A child event with its own entrant list, feeding its parent. | `event.parent_id` |
| Entrant | Who competes in an event: a player, or a pre-made team. A drafted GNL team is a roster row, not an entrant. | `event_entrant` |
| Side | The players on one side of a series, with a race each. | `series_side` |

# Words with history

- **Season** is the GNL word for a GNL event. The payloads keep `season_id`, `seasons`, `playday` and `phase`, and the class is `Season`, because the frontend, the WordPress shortcodes and the Discord cards read those names. The table underneath is `event`.
- **Match** is the GNL admin word for a fixture. The table is `matches`. Never use "match" for a series in new text.
- **Week** is deprecated in favour of round. A round has a number and a date window; "week" survives only in a few old field names.
- **Team series** is never used. A fixture holds series.
- **Fantasy Captain** is the person who drafts a fantasy team, in every user-facing string. The API field stays `captain_id`. This person is a member who owns a fantasy team, not a GNL team captain. See [roles](roles-and-permissions.md).
- **Captain** is a GNL team captain: a seat in `team_season_captain` for one team in one season.
- **KOTH** is King of the Hill: one night, three MMR brackets, a chain of challengers per bracket. See [KOTH](koth.md).
- **W3C** and **w3champions** are the ranked 1v1 ladder service the app reads MMR and matches from. The page is called "W3C Ladder", never "Ladder", because people also play the Battle.net ladder.

# Races

`Race` is an enumeration of the four races plus Random. A player signs a season up on one race, the **signup race**, which is the race the league scores them on. Their profile `race` is a cosmetic main race and a form default; it decides nothing. A series may record a per-side **off race** when a player played another race in that one series. See [series reporting](series-reporting.md).
