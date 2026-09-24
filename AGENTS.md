# Guide for agents and contributors

## The knowledge bundle in `docs/okf/`

`docs/okf/` is public. Read [how the bundle is written](docs/okf/conventions/okf-bundle.md) before you change it. This file is the list of what never goes in, and the check to run before a commit. A pull request that changes a route, a table, a contract or a decision updates the concept in `docs/okf/` that states it, in the same pull request.

### What never goes in

- **A person.** No name, handle, email, nationality, location, machine, in-game name or team name. No role plus action plus date that together point at one individual. Write "the maintainers".
- **A conversation.** No quote, and no sentence about what people wanted, agreed, settled, considered or rejected. State the rule as it stands. A decision keeps its date and its why, one sentence each.
- **A value.** No token, password, connection string, hostname, bucket, database, project, guild, channel, role or account id, and no default credential, even a local one. An environment variable name is fine. Its value never.
- **A posture.** Nothing about which safeguards exist or are missing, which checks are on or off, what is reachable from where, what data an environment holds, or which plan, quota or cost applies. Write the operator instruction instead.
- **A weakness.** No unfixed defect, bypass or lost data. Open an issue with the detail. The bundle states the rule that holds once it is fixed.
- **Another organisation.** The vendors the code depends on are fine: Vercel, Supabase, Clerk, Cloudflare, GitHub, Discord, W3Champions. No other site, community, sponsor or person.

### Before you commit

1. Read your own diff once as a stranger on the internet. For each sentence ask: does it name a person, tell a story, hold a value, describe a posture, or expose a weakness? Rewrite it as the current rule.
2. Run `uv run just test`. The bundle test fails on an id-shaped number, an email, a connection string, a token, a deployment hostname or an IP address. It cannot see meaning. Step 1 is the real check.
3. A change to a fact the bundle states changes the concept in the same pull request and updates `generated.at`.

The review that merges the pull request repeats step 1.

## Working in this repository

- `uv run just test` runs the suite, `uv run just lint` formats and lints, `uv run just typecheck` runs ty. CI runs all three.
- The code rules live in the bundle: [layering](docs/okf/conventions/layering.md), [code style](docs/okf/conventions/code-style.md), [testing](docs/okf/conventions/testing.md), [git and pull requests](docs/okf/conventions/git-and-pull-requests.md).
- A route a consumer reads costs the database once per call that misses the edge cache. Before adding or widening one, read [what a read costs](docs/okf/api/overview.md#what-a-read-costs) and [the consumer rules](docs/okf/api/consumers.md#rules-a-consumer-follows); the pull request states the rows per call and the cache time.
- `just okf-validate` checks the bundle with a third-party OKF validator. `just okf-drift` lists the concepts to re-read after a code change.
