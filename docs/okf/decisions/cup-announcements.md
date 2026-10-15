---
type: Decision
title: Cups announce to members who opt in
description: A cup posts four messages in one announcement channel, each pinging one announcement role; members take or leave that role on Home, and no role binding or sync touches it.
tags: [discord, events]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-15T11:30:00Z }
sources:
  - id: source
    resource: Maintainers' decisions, 2026-10-14
    title: Cup announcements
  - id: service
    resource: ../../../app/services/cup_announcements.py
    title: The cup announcements
---

# Decision

Since 2026-10-15, a cup posts four messages in the channel the `announcement_channel_id` setting names, and each pings the role `announcement_role_id` names:

1. the cup takes signups;
2. the cup, or a round of a cup played over rounds, starts within the hour: check in;
3. the cup is drawn, or one more round or stage of it is drawn;
4. the cup is over, with its top three.

A member takes or leaves the role with a switch on Home; Discord offers no button for it. GNL seasons, KOTH nights and sign-up lists announce nothing here.

# Why

Members who want to hear about every cup opt in once, and the rest of the guild is never pinged. The switch lives in the app, where a member already manages the events they play.

# Consequences

- Each message is a [discord_post](../data/tables/discord_post.md) row of its own kind, which is what makes it go out once. A redraw, a second publish and a second close post nothing new; a second close edits the top three card.
- [announcement_subscriber](../data/tables/announcement_subscriber.md) records who opted in. The role is not a [role binding](app-managed-roles.md): the operator binds it to no role kind, as [Discord setup](../runbooks/discord-setup.md) says, so the role sync never takes it back.
- A cup series still posts no card of its own; the messages are about the cup.
