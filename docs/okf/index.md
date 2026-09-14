---
okf_version: "0.2"
---

# wc3-gym-backend knowledge bundle

This directory is an [Open Knowledge Format](https://github.com/GoogleCloudPlatform/open-knowledge-format) bundle for the backend of the Warcraft Gym league app. Start with [the repository overview](overview.md), then read the directory that fits your question. Every file is one concept with YAML frontmatter; [how this bundle is written](conventions/okf-bundle.md) explains the fields, the links and the rule for other repositories.

# Sections

* [Overview](overview.md) - The FastAPI backend of the Warcraft Gym league app, on Vercel with a Supabase Postgres, serving the web app, the WordPress site, the Discord adapter and Nightbot.
* [conventions](conventions/index.md) - The rules the code and the pull requests follow: style, layering, git, testing, and this bundle.
* [concepts](concepts/index.md) - The domain and the integrations: vocabulary, the GNL season, the events module, KOTH, roles, fantasy, scores, the ladder, scheduling, reporting, Discord, W3Champions, storage, settings.
* [data](data/index.md) - The model families, the tables and the migration rules.
* [api](api/index.md) - The route areas, authentication, the consumers and their contract tests, the scheduled jobs.
* [runbooks](runbooks/index.md) - Run locally, deploy, seed, set up Discord, back up.
* [decisions](decisions/index.md) - What was decided, when, why, and what it means for new code.
* [pitfalls](pitfalls/index.md) - Mistakes made once, with the rule that avoids each.

# Neighbouring bundles

The app is three repositories. Each carries its own bundle at `docs/okf/`. This bundle names the others only through their contracts (routes, headers, environment variable names, payload shapes), never through a file path into them.

* `wc3-gym-frontend` - https://github.com/Warcraft-Gym/wc3-gym-frontend - the Vue web app that consumes this API.
* `wc3-gym-discord-bot` - https://github.com/Warcraft-Gym/wc3-gym-discord-bot - the Discord interactions adapter and the cast-reminder worker.

# Other documents in this repository

* [README](../../README.md) - Setup, the environment variable table, running, migrations, paging.
* [Pictures](../PICTURES.md) - Where pictures live and why.
* [Preview databases](../PREVIEW-DATABASES.md) - How every pull request gets a database.
