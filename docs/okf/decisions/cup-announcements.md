---
type: Decision
title: Cups announce to members who opt in
description: A cup posts four messages in one announcement channel, each pinging one announcement role; members take or leave that role on Home, and no role binding or sync touches it.
tags: [discord, events]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-25T18:00:00Z }
sources:
  - id: source
    resource: Maintainers' decisions, 2026-10-14
    title: Cup announcements
  - id: service
    resource: ../../../app/services/cup_announcements.py
    title: The cup announcements
---

# Decision

Since 2026-10-14, a cup posts four messages in the channel the `announcement_channel_id` setting names, and each pings the role `announcement_role_id` names:

1. the cup takes signups;
2. the cup, or a round of a cup played over rounds, is called to check in: an hour before its check-in closes early, else an hour before it starts, or when its check-in opens if that is later, while it is not drawn;
3. the cup is drawn, or one more round or stage of it is drawn;
4. the cup is over, with its top three.

A member takes or leaves the role with a switch on Home; Discord offers no button for it. GNL seasons, KOTH nights and sign-up lists announce nothing here.

Since 2026-10-25, the draw and every series set after it ping the players of those series, a team's captain for a team, instead of the role. Each series names its game name, its host (side 2, the last seat of a lobby) and a link to its veto. A member who has not chosen is asked once at a cup sign-up: subscribe, not now, or no and not again; leaving the role on Home counts as no.

# Why

Members who want to hear about every cup opt in once, and the rest of the guild is never pinged. The switch lives in the app, where a member already manages the events they play. A player in a draw needs to know their own series at once, whether or not they took the role, so the draw pings them by name.

# Consequences

- Each message is a [discord_post](../data/tables/discord_post.md) row of its own kind, which is what makes it go out once. A redraw, a second publish and a second close post nothing new; a second close edits the top three card.
- [announcement_subscriber](../data/tables/announcement_subscriber.md) records who opted in. The role is not a [role binding](app-managed-roles.md): the operator binds it to no role kind, as [Discord setup](../runbooks/discord-setup.md) says, so the role sync never takes it back.
- A later series is called in a `cup_series` message of its own once its sides stand, and a corrected pairing marks the old message changed and is called again, since an edit pings nobody.
- [announcement_subscriber](../data/tables/announcement_subscriber.md) keeps a `declined` row for a member who said no, so the sign-up question never comes back.
