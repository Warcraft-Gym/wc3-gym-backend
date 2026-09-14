---
type: Decision
title: Vercel and Supabase
description: The backend runs as one Vercel function on a Supabase Postgres, and the self-hosted Azure line is frozen.
tags: [decision, hosting]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: source
    resource: Maintainers' decisions, 2026-08-25 to 2026-09-03
    title: The hosting move
---

# Decision

Since 2026-08-30 the live backend is this repository on Vercel, with the database on Supabase. The older self-hosted line (a Docker Compose stack on an Azure VM, reached through Portainer) is frozen in a fork and this repository does not support it. Never plan a Docker, nginx or VM fallback here; a leftover such as the Dockerfile only serves local development.

# Why

The self-hosted line was deployed by hand on a shared machine. Vercel builds every merge and every pull request; Supabase runs Postgres without a server to keep. Clerk sessions and the Discord roles made the Vercel line diverge from anything that could merge back.

# Consequences

- One function serves every route; a second Python file in `api/` is not built. A separate small service is a separate project, which is why the Discord adapter is its own repository.
- The function limit is 60 seconds and the Hobby plan runs one cron a day. See [jobs](../api/jobs.md).
- The database is reached through the transaction pooler on port 6543. See [the pitfall](../pitfalls/transaction-pooler.md).
- The Supabase free plan meters egress across every service; bytes leaving the database are the cost to watch. See [the pitfall](../pitfalls/blob-egress.md).
- Vercel and Supabase sit in the same US East region on purpose; the first project sat in Europe and cost about 80 ms per statement.
