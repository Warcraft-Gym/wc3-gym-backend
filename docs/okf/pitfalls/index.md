# Pitfalls

* [A .env loaded below the entry point reaches the tests](env-loading-in-tests.md) - load_dotenv with no path walks up from the file, so a worktree loaded a .env above it and the suite made real Discord calls.
* [A boundary test that drives the oracle proves nothing](test-drives-the-oracle.md) - 71 careful boundary cases passed while the production SQL rule was broken, because the test called the Python copy in the test folder.
* [A bytes column drives egress](blob-egress.md) - A picture stored as bytes on a row is read by every query that touches the row, invisible to statement counts and response sizes, and it drove database egress.
* [A column drop needs two deploys](column-drop-two-deploys.md) - The production build migrates while the previous code still serves, so a dropped column breaks every request of the old code until the promotion.
* [A Hobby cron runs once a day](hobby-cron-daily.md) - A vercel.json schedule more frequent than daily fails every deployment with no build log, and production silently stays on the previous build.
* [A replay does not give up the winner](w3g-winner-not-parseable.md) - A .w3g yields the map and the battle tags from its first block; the winner is not readable, and a hand-written record walker was rejected.
* [Every datetime is aware UTC](datetimes-are-utc.md) - A stale log line said the backend stored Eastern time and cost a whole wrong work package; times are UTC, stored aware, and the public site once added five hours.
* [just vercel seed defaults to production](seed-defaults-to-prod.md) - The seed recipe truncates every table and reloads a dump, and its environment argument defaults to prod.
* [One schema per entity wipes columns](one-schema-wipes-columns.md) - A single model serving create, update and response made every field optional, and an update wrote every column, nulling the ones the request left out.
* [pytest walks up to the parent checkout](pytest-walkup.md) - An empty pytest table in pyproject.toml makes pytest adopt an ancestor directory as its root, which in a nested worktree is the main checkout.
* [Quoting a whole relationship annotation breaks every mapper](sqlmodel-relationship-quoting.md) - A SQLModel Relationship annotated as the string "X | None" hands SQLAlchemy an opaque name; X | None works when X is imported, and Optional["X"] is the only quoted form.
* [The edge cache stores the CORS header](edge-cache-cors.md) - A publicly cached route filled by a client with no Origin header is stored without the CORS header, and every browser then blocks it.
* [The guild setting is a decision, not a bug](prod-guild-is-test-guild.md) - A member classified as a guest is a membership question about the configured guild; changing the guild setting is a maintainers' decision, never a bug fix.
* [The ladder table is the egress driver](ladder-egress.md) - Reading a whole season window of ladder matches on every view grows through a season and multiplies with viewers.
* [The session pooler holds 15 clients](transaction-pooler.md) - Serverless functions on the session pooler fill its 15 slots with idle connections and every other request answers Database error; use the transaction pooler on port 6543.
* [The staging URL is not the served database](staging-url-wrong-db.md) - The staging connection string names the anchor database, which holds no app tables; the preview serves from the shared staging database or a branch copy.
* [Two Alembic heads after a squash](alembic-two-heads.md) - Two branches that each add a migration on the same parent leave two heads on main after the second squash, breaking CI and the staging migrate job.
* [Vercel CLI traps](vercel-cli-traps.md) - Three ways a CLI deploy goes wrong: no token, a worktree without the project link, and a commit author outside the team.
