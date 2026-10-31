---
type: Decision
title: The backend signs members in with Discord
description: Members sign in with a Discord OAuth flow the backend runs, and the backend signs their session token; the guild check and the roles stay app code.
tags: [auth]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-27T12:00:00Z }
sources:
  - id: source
    resource: Maintainers' decision, 2026-10-27
    title: Discord login without a session service
---

# Decision

Authentication is a Discord OAuth authorization-code flow that the backend runs, `GET /auth/discord/start` and `GET /auth/discord/callback`, scope `identify`. The callback signs a session token with `JWT_SECRET_KEY` that names the Discord account and lasts 30 days. The backend reads the guild membership and the role on every request. The admin token login stays for the admin UI and scripts.

# Why

Discord is the only way a member signs in, so a session service in front of it added a second vendor, a proxy and an outside call on every login for what one OAuth flow and a signed token do.

# Consequences

- The guard ladder `require_login < require_member < require_admin` and the guild read stay app code, unchanged.
- A session ends when its token expires, or after a day for an admin; signing out drops it in the browser. A session that must end sooner needs a sessions table, which a later change adds when it is needed.
- Every deployment that signs members in has its `/auth/discord/callback` listed as a redirect of the Discord application.
- Battle.net is a linked proof on a tag, never a login, and runs the same kind of flow; see [authentication](../api/auth.md).
