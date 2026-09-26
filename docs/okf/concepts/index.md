# Concepts

* [Derived scores](derived-scores.md) - Series points, fixture scores, standings, career ratings and fantasy scores are computed from the map scores on every read, in a constant number of statements.
* [Discord integration](discord-integration.md) - Slash commands arrive through a separate adapter and are checked and answered here, cards are posted and edited under a rate limit, and season roles are mirrored to the guild on a button press.
* [Edge cache](edge-cache.md) - Every open read the edge caches uses one of three timer classes, live, running or settled, and an event read picks running or settled from the event's phase; nothing is purged.
* [Events module](events-module.md) - One data model for every kind of event, with GNL and KOTH behaviour in their own modules on top, a stage engine that never branches on kind, a phase derived on every read, and the admin's path from a new league to a finished event with awards.
* [Fantasy league](fantasy.md) - A member drafts players, one team and one race for a season, places bets on series, and scores six derived parts.
* [GNL season](gnl-season.md) - Six drafted teams, five weekly rounds, one fixture per team pairing with captain-drafted series, and a phase that is derived from the series.
* [KOTH night](koth.md) - A King of the Hill night is one event of the KOTH league with three MMR brackets as divisions, one signup rule at every door, and every series paired by hand while the night runs.
* [Pictures and replays](pictures-and-replays.md) - Team logos and map thumbnails live in Vercel Blob as public URLs, replays live in a Cloudflare R2 bucket reached through presigned URLs, and both stores follow the rows.
* [Roles and permissions](roles-and-permissions.md) - Four roles decided by the database and the guild, ownership checked per row, reads open and writes admin-only, and an admin view-as switch.
* [Scheduling and availability](scheduling-and-availability.md) - A player answers whether they can play a round, keeps soft blocks that inform but never constrain, and a pair's shared free time is read as intervals for a series and as one count before one exists.
* [Series reporting](series-reporting.md) - A result is reported game by game with a map and a replay per game, a veto board that is derived from the season rules, an off race per side, and casts that any member may claim.
* [Settings and the current season](settings-and-current-season.md) - A key-value table holds the few runtime values an admin edits, including the two season pointers, and a missing row falls back to the newest season.
* [Vocabulary](vocabulary.md) - One word per thing, from league down to game, and the words this app keeps for old reasons.
* [W3C ladder and achievements](ladder-and-achievements.md) - Every ranked 1v1 match of a GNL player is stored once, scored per season on their signup race, and 24 badge rules run as one SQL union.
* [W3Champions](w3champions.md) - The ranked ladder service the app reads MMR, per-race stats and match history from, with a timeout, a throttle answer, and two separate sync pipelines.
