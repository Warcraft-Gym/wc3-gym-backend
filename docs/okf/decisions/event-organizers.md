---
type: Decision
title: Organizers run small events
description: A member an admin granted creates cups and runs the ones it holds a row of; organizers are Discord accounts, and GNL seasons and KOTH nights stay the admins'.
tags: [auth, events]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-05T18:00:00Z }
sources:
  - id: source
    resource: Maintainers' decisions, 2026-10-05
    title: Event organizers
---

# Decision

Since 2026-10-05, an organizer is a Discord account with a grant, held only while it is a member of the guild. It creates small events and runs each event it holds an `event_organizer` row of, beside the admins. A member asks for the grant on the Events page and an admin answers the request. The grant is a capability, not a fifth role, and running an event is an ownership check.

# Why

Short community tournaments need more hands than the admins have, and none of those hands should reach a GNL season or a KOTH night.

# Consequences

- An organizer needs no player row and no battle tag, only a Discord login, as an admin does.
- The guards decide by ownership, never by kind: a GNL season and a KOTH night hold no organizer row, so their writes stay the admins'. See [one event model](unified-event-model.md).
- An organizer's event write stays inside a small event: a `cup` or `signup` kind, no league or a `custom` one, no event Discord role, no `gnl` or `koth` stage.
- Posting into a Discord channel stays an admin's, because the post names any channel.
- A revoked grant stops new events; the rows of the events the account runs stay until a runner removes them.
