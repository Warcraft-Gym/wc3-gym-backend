---
type: Decision
title: Discord's edit limit is a core constraint
description: Every channel post and edit goes through the discord_post rows, which pace edits to Discord's five per five seconds per channel and collapse a burst to its last state.
tags: [decision, discord]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: source
    resource: Maintainers' decision, 2026-09-08
    title: Manage the edit limit as a core constraint
---

# Decision

`discord_posts.refresh_series` claims an edit with one UPDATE, waits when the channel had an edit in the last second, retries a bounded number of times, and skips a post already edited after its latest change. `discord._channel_call` waits out one 429.

# Why

Eight veto steps in two seconds edited every card eight times; Discord refused past the limit and a refused edit was lost.

# Consequences

- A new post or edit goes through `discord_posts`, or at least `discord._channel_call`.
- Never a loop of edits per write, never an in-memory queue or lock: no process survives a request on Vercel.
