# Tables

The 47 tables, one concept each. A concept's `# Schema` lists every column; `tests/test_okf.py` fails when the columns and the concept disagree.

# People and access

* [users](users.md) - One person, made by the first way in that meets them and found by any battle tag they hold or by Discord id, with the profile fields the forms write and three sync stamps.
* [user_battle_tag](user_battle_tag.md) - One battle tag a person has played under; a tag names at most one person, and each person has at most one active tag.
* [link_prompt](link_prompt.md) - A suggestion that an earlier player is a login, answered once by that login, or the notice that another login verified a tag and took it.
* [clerk_account](clerk_account.md) - The Discord account behind one Clerk user, written on the first guarded request of a login so no later request asks Clerk.
* [admin_grant](admin_grant.md) - One Discord account that administers the site, granted on the Config page; the bootstrap ids in ADMIN_DISCORD_IDS need no row.
* [settings](settings.md) - One key-value row per runtime setting an admin edits, including the two season pointers and the Discord channel ids.
* [user_block](user_block.md) - One standing weekly block of a player, as local wall-clock times on a set of weekdays; a soft hint that informs scheduling and never constrains it.
* [user_busy](user_busy.md) - One one-off busy range of a player, as whole local days with both ends included; a soft hint like a weekly block.

# Leagues and events

* [league](league.md) - One thing that repeats, such as the GNL or KOTH; each run of it is an event.
* [event](event.md) - One run of a league that people sign up for: a GNL season, a KOTH night, a cup or a sign-up list; the class is still named Season.
* [event_stage](event_stage.md) - One format played over the entrants of an event, with the points, the tie breaks and the advance rule; standings are computed from it, never stored.
* [event_round](event_round.md) - One round of a stage: its number, its date window and the fixed map of game 1; a GNL playday is a round.
* [event_division](event_division.md) - One MMR band of an event that runs the whole stage list on its own and never merges; a KOTH bracket is a division.
* [event_entrant](event_entrant.md) - One player or one pre-made team in one event, with its race, seed, division, check-in and withdrawal stamps; a withdrawn entrant keeps its row.
* [event_award](event_award.md) - One place of a finished event, frozen from the table of its last stage when an admin closes it; a trophy read lists these rows.
* [matches](matches.md) - One fixture: two teams meeting in one round of an event, which the series between their players hang under.
* [series](series.md) - One series between two sides, a best-of with its scores, time, host, off races, result kind and the feeder graph a bracket runs on.
* [series_side](series_side.md) - One seat of a series that is not a plain 1v1: a player in an FFA lobby or on a team side, with the place that side finished.
* [series_game](series_game.md) - One game of a series with the side that won it and the map it was played on, because a 2-1 score alone cannot say which.
* [series_replay](series_replay.md) - One replay slot per game of a series, holding the object key of the file in the replay bucket and who uploaded it.
* [series_veto_step](series_veto_step.md) - One taken step of a series' map veto, with the side, the action, the map and who entered it; the order itself comes from the event's pick_ban.
* [series_cast](series_cast.md) - One member's claim to cast one series, with the channel it streams on and the VOD pasted after; planned, live and VOD states derive at read time.
* [draft_series](draft_series.md) - One series a captain proposed inside a GNL fixture, held apart from the series table until an admin promotes it.
* [match_draft_mark](match_draft_mark.md) - One team's advisory Ready mark on the draft of one fixture, plus the moment that team last read the pairings.
* [match_draft_state](match_draft_state.md) - The working largest MMR difference the captains pair inside while they draft one fixture, which stands in front of the stage setting.
* [round_availability](round_availability.md) - One player's answer to whether they can play one round of an event; no row is no answer, and clearing an answer deletes the row.

# Teams and rosters

* [teams](teams.md) - One league-owned team: its league, short name, long name and the public URL of its logo.
* [team_season](team_season.md) - One team fielded in one GNL season; the row exists before the team has a captain or a roster.
* [team_season_captain](team_season_captain.md) - One captain seat: a player who captains one team in one season; the seat is what makes an account a captain.
* [user_team_season](user_team_season.md) - One roster row: a player on one team in one season, written by the draft.
* [user_season_signup](user_season_signup.md) - One GNL signup: a player registered for one season on one race, with the draft order and fantasy tier an admin sets.

# Maps

* [maps](maps.md) - One map: its name, its short name and the public URL of its picture.
* [map_season](map_season.md) - One map in one event's pool, with its place in the pool order.

# Fantasy

* [fantasy_teams](fantasy_teams.md) - One Fantasy Captain's team for one season: the real team, the race and the grind pick it drafted; every score derives.
* [fantasy_team_player](fantasy_team_player.md) - One player drafted onto one fantasy team.
* [fantasy_bets](fantasy_bets.md) - One stake of points a member placed on one series and the player they called to win it.

# W3Champions

* [w3cstats](w3cstats.md) - One player's 1v1 record on W3Champions for one race in one W3Champions season, as the stats sync last read it.
* [w3c_ladder_matches](w3c_ladder_matches.md) - One ranked 1v1 W3Champions match of one GNL player, with the selected and the played race on both sides; points and badges derive from it.
* [ladder_sync](ladder_sync.md) - The ledger of the match sync: one row per player per W3Champions season saying when it was read, from when, and whether the read reached the end.
* [ladder_achievements](ladder_achievements.md) - One price for one achievement rule in one season, or for a player's lifetime when the season is null; the rule itself is code.
* [player_career_stats](player_career_stats.md) - One player's baseline from the seasons played before the app, imported from a CSV and never edited; the career totals add the app's seasons on every read.

# Operations

* [egress_ledger](egress_ledger.md) - What each route cost the database, one row per day, route and method: calls, statements, rows and response bytes.
* [egress_snapshot](egress_snapshot.md) - One daily copy of pg_stat_statements: each statement's cumulative calls and rows at the time of the copy, kept 35 days.
* [egress_statement](egress_statement.md) - The text of each statement in egress_snapshot, stored once: the first 150 characters with whitespace collapsed.

# Discord

* [discord_role_binding](discord_role_binding.md) - One binding of a role kind and scope to a guild role, so the sync can grant and take back that role from what the database says.
* [discord_role_hidden](discord_role_hidden.md) - One guild role an admin marked as none of the app's business, so the binding page hides it and it can never be bound.
* [discord_post](discord_post.md) - One card the app posted in Discord and may edit later, with the two stamps that pace edits to the channel's rate limit.
