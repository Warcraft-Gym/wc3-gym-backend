---
type: Pitfall
title: A .env loaded below the entry point reaches the tests
description: load_dotenv with no path walks up from the file, so a worktree loaded a .env above it and the suite made real Discord calls.
tags: [deploy, testing]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: source
    resource: ../../../tests/conftest.py
    title: The keys the suite removes
---

# What happened

`create_app` and the migration environment called `load_dotenv()`. In a worktree under the checkout that walked up to a `.env` above it. The suite then made real Discord calls, and the outbound-call guard failed 62 tests, only where such a file existed.

# The rule

- A `.env` file is read only at the entry points: `api/index.py` and the `just` modules. `create_app` reads the process environment.
- An environment key that turns a network call on is removed in `tests/conftest.py` at import. Add a new one there when the guard starts refusing calls.
- Never add `load_dotenv` to a module the tests import.
