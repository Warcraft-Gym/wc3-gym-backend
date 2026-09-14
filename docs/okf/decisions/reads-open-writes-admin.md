---
type: Decision
title: Reads open, writes admin
description: Every GET serves any session; writes need an admin or the owning member, and the frontend hides the buttons of writes a role cannot make.
tags: [decision, permissions]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: source
    resource: Maintainers' decision, 2026-08-31
    title: Open the ladder reads
---

# Decision

Read routes serve guests, members and admins alike. Write routes keep `require_admin`, except a member's own flows, which the service checks for ownership. The frontend hides a write's button behind the role rather than letting the call fail.

# Why

The admin gates on reads were leftovers from before Clerk. Hiding the button matters because the frontend's fetch wrapper ends the session on a 401; a visible button that fails would log people out.

# Consequences

- A new GET needs no guard unless it answers something personal.
- A sync or import stays admin-only in the route and in the button.
- Ownership is a row check in the service, never a role. See [roles](../concepts/roles-and-permissions.md).
