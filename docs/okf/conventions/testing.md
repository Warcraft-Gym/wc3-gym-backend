---
type: Convention
title: Testing
description: The suite migrates a temporary SQLite file with Alembic, opens no socket, and holds guard tests that pin contracts, statement counts and memory.
resource: ../../../tests/conftest.py
tags: [testing]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: conftest
    resource: ../../../tests/conftest.py
    title: The shared fixtures and their rules
  - id: migrate
    resource: ../../../tests/migrate.py
    title: How the suite builds its database
---

# How the suite runs

- `uv run just test` runs pytest the way CI does. Pass pytest arguments through: `uv run just test -k koth`.
- The suite builds a temporary SQLite file with `alembic upgrade head`, the same command a deployment runs, so every run also checks the migrations. Tests share one database and a fixture empties it between tests.
- `tests/conftest.py` is the only module that imports the web framework. Every test asserts on status codes and JSON through the `client` fixture, or calls a service directly.
- The suite opens no socket. A fixture fails any outgoing call a test did not stand in for. An environment key that turns a network call on (`DISCORD_BOT_TOKEN`, `DB_URL`) is removed from the process at import time in `conftest.py`. Never add `load_dotenv` to a module the tests import.
- To run the same suite on Postgres, set `TEST_DB_URL` to a server whose user may create databases. Postgres-only questions (collation, casting, sequences) are settled there, not on SQLite.

# Guard tests

These tests encode a lesson each. Keep them green and extend them when the lesson applies to new code.

| Test | What it guards |
|---|---|
| `test_migrations.py` | the models and the migrated schema describe the same tables; one Alembic head |
| `test_error_envelope.py` | every error answers `{"error": ...}` and a 500 exposes nothing |
| `test_public_contract.py` | the fields the WordPress shortcodes read from eight routes |
| `test_contract.py` | the fields the offline leaderboard reads |
| `test_gnl_snapshot.py` | the GNL season payloads, byte for byte, against `tests/data/gnl_snapshot.json` |
| `test_query_budget.py` | the number of SQL statements one list answer costs is a constant |
| `test_memory_budget.py` | the peak memory of the fantasy bets list |
| `test_blob_budget.py` | no mapped binary column exists; a picture is a URL |
| `test_natural_keys.py` | the unique keys the importers match on |
| `test_utc_default.py` | every datetime is aware UTC on every dialect |
| `test_achievement_parity.py` | the SQL achievement rules and the Python oracle agree on the same boundary cases |
| `test_paging.py` | every paged route, its default order and its sort names |

# Oracles

Some rules have two faces: SQL for aggregates and Python for loaded rows, or a Python oracle in `tests/` beside a SQL rule in `app/core`. A boundary test proves nothing about production when it drives only the copy. Feed the boundary cases through both faces. See [the pitfall](../pitfalls/test-drives-the-oracle.md).

# Real data

`tests/data/` holds two season workbooks and captured W3Champions pages. The workbook round trip and the ladder parser run against them, so a change to the import or the sync is checked against the real shapes.
