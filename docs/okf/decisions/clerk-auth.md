---
type: Decision
title: Clerk owns the session
description: Members sign in through Clerk with Discord as the only social connection; the guild check and the roles stay app code.
tags: [auth]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: source
    resource: Maintainers' decision, 2026-08-29
    title: Go Clerk
---

# Decision

Authentication is Clerk: the OAuth exchange with Discord, the session token, its refresh and its revocation. The backend verifies the session with the Clerk SDK and then resolves the Discord id, the guild membership and the role itself. The admin token login stays for the admin UI and scripts.

# Why

The maintainers want a library to own session management rather than a custom token and cookie stack to support.

# Consequences

- Do not re-argue direct OAuth against Clerk.
- Keep the guard ladder `require_login < require_member < require_admin` and the guild read as app code. Only the token is Clerk's.
- Production runs the Clerk production instance in proxy mode through the frontend; previews and local use the dev instance. A preview must never point at the production backend.
- The Clerk user to Discord id link is one row, written on the first request of a login and read after that.
- Battle.net linking, when it comes, is a custom OIDC connection on Clerk.
