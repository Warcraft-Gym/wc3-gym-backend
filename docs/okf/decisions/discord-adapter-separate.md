---
type: Decision
title: The Discord adapter is its own small app
description: Discord interactions land on a one-route Starlette app in a separate repository that verifies and forwards; the backend does the work.
tags: [decision, discord]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: source
    resource: Measured cold starts, 2026-09-05 and 2026-09-06
    title: The adapter's cold start
---

# Decision

Discord posts to the adapter in `wc3-gym-discord-bot`, which checks the signature, answers a deferred reply inside Discord's 3 second window, and forwards the payload to `POST /discord/interactions`. The backend checks the signature again and runs the command. The adapter holds no bot token and knows no command.

# Why

Measured after idle, a one-file Python function cold-starts in about 0.85 s and the backend app in about 4 s, past Discord's window. The Vercel FastAPI preset builds one function and does not build a second file, so the adapter cannot live in this project. Starlette was chosen over FastAPI for the adapter because FastAPI's import alone costs 0.4 s.

# Consequences

- The command list and every reply live here; the adapter changes only when the handshake changes.
- A Starlette background task on the response is the after-response hook on Vercel Python; the forward runs there within the 60 second limit.
- Autocomplete has no deferred form; the adapter waits 2 seconds and answers an empty list on a timeout.
