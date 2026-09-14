---
type: Convention
title: How this bundle is written
description: The rules for every file under docs/okf, and the one rule for talking about the other repositories.
tags: [okf, documentation]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: okf-spec
    resource: https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/main/SPEC.md
    title: Open Knowledge Format v0.2 specification
---

# What this bundle is

`docs/okf/` is an Open Knowledge Format (OKF) bundle: a directory of markdown files with YAML frontmatter, readable by a person and by an AI agent. Each file is one concept. The file path is the concept id. `index.md` lists a directory and `log.md` records changes; every other `.md` file is a concept.

The bundle exists so that a new contributor, human or agent, can read how the app works, why it works that way, and which mistakes were already made, without asking the people who built it.

# Frontmatter

Every concept starts with a YAML block. `type` is required. The types this bundle uses:

| type | What the file holds |
|---|---|
| Repository | the one overview of this repository |
| Convention | a rule the code follows |
| Domain Concept | a thing the league runs on, and how the app models it |
| Data Model | tables and model families |
| API Area | a group of routes and their rules |
| Integration | how this repository talks to a service outside it |
| Runbook | steps to do one operational task |
| Decision | a choice that was made, when, and why it stands |
| Pitfall | a mistake that was made once, and how to not repeat it |

The other fields: `title`, `description` (one sentence), `tags`, `generated: { by, at }` (who wrote the current text and when), `verified: [{ by, at }]` (who checked it against the code), `status` (`draft`, `stable` by default, `deprecated`), `stale_after`, and `sources` (what the text was written from).

`generated.by` names the writer: `human:<github handle>` for a person, `<tool>/<model>` for an agent. A concept with no `verified` entry is unverified. When a maintainer reads a concept against the code and finds it true, they add a `verified` entry with their own handle. Nobody adds one for someone else.

# Sources and links

A concept names what it was written from in `sources`. A source inside this repository is a relative path from the concept file, for example `../../../app/api/deps.py`, so the link works on GitHub and survives a rename of the repository. A source outside the repository is a URL, or a short description when there is no URL, for example `Maintainers' decision, 2026-09-08`.

Links between concepts are relative markdown links, for example `../decisions/derived-not-stored.md`. The OKF spec prefers bundle-absolute links that start with `/`. This bundle uses relative links because GitHub renders them and bundle-absolute ones break there.

# The one rule about other repositories

The app is three repositories: the backend, the frontend and the Discord adapter. Each has its own bundle. A bundle describes only what its own repository proves, plus the decisions that shaped it.

A shared fact is owned by one repository:

- the backend owns the domain model, the API contract, the roles, the settings keys and the environment variable names it reads;
- the frontend owns its pages, its design rules and the way it consumes the API;
- the Discord adapter owns the interaction handshake and the cron worker.

Another repository is named only through its contract: an HTTP route, a header, a query parameter, an environment variable name, a Discord payload shape. Never a file path into another repository, and never a link to a file in another bundle. Those paths move without telling anyone.

Each bundle's `index.md` has one section, "Neighbouring bundles", that names the other repositories by their GitHub root. That is the only cross-repository pointer, one line per neighbour, so a moved repository costs one line in each neighbour.

Where a concept must be understood on both sides, the consuming repository writes a short "as consumed here" concept that names the fields it relies on, and says in prose which repository owns the definition. It does not copy the definition.

Tests keep the two sides in step, not prose. The backend pins the response shapes its consumers read in `tests/test_public_contract.py`, `tests/test_contract.py`, `tests/test_gnl_snapshot.py` and `tests/test_error_envelope.py`. A change to one of those tests is a change to a contract and needs a change in a consumer.

# Writing

Write short sentences: one fact per sentence, the present tense, the active voice. Say what is, not what used to be. A decision says when it was made and why. Never name a person and never quote one: write "the maintainers" and summarise what was concluded.

The bundle is public. Never write a secret, a token, a database URL, an account or guild id, or any detail about a person into it. The full list of what never goes in, and the check to run before a commit, is [`AGENTS.md`](../../../AGENTS.md) at the repository root.

# Keeping it true

- A pull request that changes a fact this bundle states changes the concept in the same pull request and updates `generated.at`.
- A concept that no longer holds gets `status: deprecated` and one line naming what replaced it. It is not deleted, so links keep working.
- `log.md` gets one line per change, newest first.
- `uv run just test` runs `tests/test_okf.py`. It checks that every concept has a `type`, that `index.md` files carry no frontmatter except the root one, and that every relative link resolves to a file.
