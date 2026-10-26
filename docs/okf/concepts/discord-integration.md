---
type: Integration
title: Discord integration
description: Slash commands arrive through a separate adapter and are checked and answered here, cards are posted and edited under a rate limit, cups announce themselves to the members who opt in, and season roles are mirrored to the guild on a button press.
resource: ../../../app/services/interactions.py
tags: [discord]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-26T16:00:00Z }
sources:
  - id: interactions
    resource: ../../../app/services/interactions.py
    title: The interactions the adapter forwards, and the command list
  - id: posts
    resource: ../../../app/services/discord_posts.py
    title: The posts the app keeps true
  - id: discord
    resource: ../../../app/services/discord.py
    title: The Discord calls and the guild read
  - id: roles
    resource: ../../../app/services/discord_roles.py
    title: The role sync
  - id: cards
    resource: ../../../app/services/series_cards.py
    title: The series cards
---

# The contract with the adapter

Discord sends every slash command, button press and autocomplete to a small adapter in the repository `wc3-gym-discord-bot`. The adapter checks Discord's Ed25519 signature, answers inside Discord's 3 second window with a deferred private reply, and forwards the payload unchanged to `POST /discord/interactions` with the same two headers, `X-Signature-Ed25519` and `X-Signature-Timestamp`. This route checks the signature again with `DISCORD_PUBLIC_KEY`, so it trusts Discord and nothing else, then runs the command and replies through the interaction token: a private edit of the deferred reply, or a public follow-up in the channel. The route answers 503 while `DISCORD_PUBLIC_KEY` is unset. Autocomplete has no deferred form; the adapter waits 2 seconds and answers an empty list on a timeout.

The adapter holds no bot token and knows no command. The command list lives here, in `COMMANDS` in `app/services/interactions.py`, and each production build registers it on the guild after the migrations (`api/discord_setup.py`); `uv run just discord-commands` does the same by hand. See [Discord setup](../runbooks/discord-setup.md).

# The commands

| Command | What it does |
|---|---|
| `/upcoming` | the series scheduled in the next days, claimed first |
| `/leaderboard` | achievement, ladder or fantasy points this season |
| `/stats` | one player's GNL season from the stored ladder and their series |
| `/announce` | the match card of one series, posted in the channel |
| `/availability` | a card for one round with one button per answer |
| `/schedule` | set the time of the caller's series |
| `/report-result` | report a result with a replay per game as optional attachments, through the same write the dashboard uses; the reply names the games saved without one |
| `/veto` | point the two players at the veto board and say where it stands |
| `/postlinks` | the site's links as buttons, posted by an admin |

Six commands have a module under `app/services/commands/`; `/upcoming`, `/leaderboard` and `/schedule` are functions in `app/services/interactions.py`. A module imports `base.py`, never `interactions.py`, which imports the modules.

# Cards and posts

The app posts a result card, a cast claim card and a start reminder, plus one card per event with Sign up and Check in buttons. Each post is a `discord_post` row so the app can edit it later. The result, cast and reminder cards go to the channels the `settings` rows `results_channel_id` and `content_channel_id` name, and a missing row means no card; the event card goes to the channel the admin names in the body of `POST /events/{id}/discord-post`. Every series write keeps the cards in step through `discord_posts.follow_series`: a new time edits the series cards, a first score posts the result card, a changed score edits it, and a cleared result deletes it with its row, so the next report posts a fresh one.

A reported result that a player or a captain changes through the report (`PUT /player-series/{id}` or `/report-result`), or takes back (`DELETE /series/{id}/result`), also gets a note beside the card in the results channel, through `discord_posts.post_result_change`. The note names who made the change, a player of the series or a captain, and shows the score before and after behind spoilers, as the card does. When the score stands, it says the games or the races played changed. A note is a `discord_post` row of kind `result_change`, so the channel's pacing counts it, and it is never edited: it records one change. An admin's write, a captain's edit through `PUT /series/{id}` and a first report post no note.

Discord allows five edits per five seconds per channel. `discord_posts.refresh_series` claims an edit with one UPDATE, waits when the channel had an edit in the last second, and skips a post already edited after its latest change, so a burst collapses to the last state. `discord._channel_call` waits out one 429. Never loop edits per write, and never use an in-memory queue or lock: no process survives a request on Vercel. See [the decision](../decisions/discord-rate-limit.md).

Card rules: a mention is a call to action, so `/upcoming` tags nobody and the reminder tags the casters and the players; the change note names its author inside the embed and allows no mention, so it notifies nobody; no database ids on a card; the round number, not the week; a player reads `{flag} {name} ({race} {mmr})` with the race played, else the signup race; every time is a Discord timestamp; the veto shows what the season's `map_rules` say.

# Cup announcements

A cup posts five kinds of message through `app/services/cup_announcements.py`: its news in the channel the `announcement_channel_id` setting names, and its draw and series in its own thread in that channel:
- **Open:** a cup that reads published with its signups open, after `POST /events`, `PUT /events/{id}` or a recurring cup made, with the event card's description and a link to sign up on the site.
- **Reminder:** `GET /jobs/cast-reminders` also calls every cup to check in, once: an hour before its check-in closes early (`checkin_closes_minutes`), else an hour before it starts, or when its check-in opens if that is later, and only while the check-in stands open and the cup is not drawn. A cup played over rounds is called round by round, each round on its own start and window; a start that has passed is not called. A cup that takes no check-in is called an hour before it starts.
- **Draw:** a stage's first draw and every later round of a stage that draws round by round, from the runner's draw, a result that draws the next round or stage, or a withdrawal. The engine marks each draw in the session, and the post goes out after the commit, so a refused draw posts nothing. It lists every series the draw set, one line each: the two sides with the host marked, side 2 or the last seat of a lobby, a link to the series' veto on the event page (`?tab=draw&veto=`), or to the draw on a custom game cup or a lobby, and last "Game Name:" with the game name, `GYM_` and the series id, in code style. The name holds no space, so a double-click marks it whole; a bye is named. A draw too long for one message goes out in several, so no ping and no line is lost to Discord's limits.
- **Series:** a later series, once a result sets both its sides or every seat of a lobby, in the same form as one line of the draw, once (`cup_series`). A series a draw set in the same write is in the draw's message already. When a corrected or cleared result takes a side back off a series already called, its message is edited to say the pairing changed and its row goes, so the new pairing is called again; an edit pings nobody.
- **Podium:** once the cup closes, by the result that plays it out, by the finish of its last round, or by `POST /events/{id}/finish`. The content pings the role, says the cup is over and congratulates the podium: a player by mention, a team by name with its captain's mention. Each place reads a credit line: the medal, the name, the place (champion, runner-up, third) and the entrant's series record over the cup; the champion's adds the final it won in an elimination bracket, with its score; a cup played over rounds reads the overall points and the rounds played instead. A cup without divisions holds it all in one card; a cup with divisions has one card per division and a closing card, and the divisions past the ninth are listed in that closing card, since a message takes ten. The last lines give the cup's figures (who played, the rounds, the series or lobbies, and the maps, a grand final's head start not counted) and a thank-you. A close after a reopen edits that message.

The open, reminder and podium messages ping the role `announcement_role_id` names; the draw and series messages ping the players of their series instead, a team's captain for a team, and a player with no Discord login is named without a ping. Every ping rides in the message content, with `allowed_mentions` naming those accounts alone; a missing channel posts nothing, and a missing role posts with no ping. Each is a `discord_post` row of its own kind and goes out once. A deleted cup drops those rows, and its messages and its thread stay.

The cup's thread opens with its first draw or series message, under its open message, or under a line of its own that pings nobody (`cup_anchor`) when the cup has none. The thread's first message says what it holds and is its `cup_thread` row, whose `channel_id` is the thread. The thread leaves the channel list a week after its last message, and the next message brings it back; a mention in it adds the player to it. When Discord opens no thread, the draw and series go to the channel itself. The bot needs Create Public Threads and Send Messages in Threads there, as [Discord setup](../runbooks/discord-setup.md) says. A member takes or leaves the role on Home, or answers the question a cup sign-up asks, with `PUT /me/announcements`; see [the decision](../decisions/cup-announcements.md).

# The guild read and the roles

An account's Discord token from Clerk only identifies it; the bot token reads the guild membership. `DISCORD_GUILD_ID` names the guild. Which guild it names is a maintainers' decision, never a configuration fix for a guest classification.

Every Discord call goes through one `requests.Session` in `app/services/discord.py`, so calls reuse a connection. `role_for` keeps each account's member or guest answer for `ROLE_TTL` seconds in the process, so a guild join or leave shows within a minute; a failed read is never kept. `app_emojis` keeps the first successful read for the life of the process and reads again after a failure.

`discord_role_binding` maps a role kind and scope to a guild role. `POST /config/discord-roles/sync` grants and revokes season roles; it never touches admin or coach roles, and it runs only when an admin presses the button. The bot's role must sit directly above the season roles in the guild's role list and below everything else, because a bot manages only roles below its own. See [roles](roles-and-permissions.md).

# Reading a Discord link

A session cannot open a `discord.com/channels/...` link, but the REST API with the bot token reads a channel or thread: `GET /channels/{id}/messages?limit=50`. The bot token is an environment value.
