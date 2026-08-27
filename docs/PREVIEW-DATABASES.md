# Preview databases

Every pull request gets a Vercel preview deployment. Vercel calls these deployments previews; the database project they use is the staging project. Previews used to run against the production Supabase database with the production admin token, so a preview of a migration served new code on the old schema, and anything written through a preview URL landed in real data. Previews now run against a separate Supabase project, the staging project, and this page says how.

## The three databases on the staging project

| Database | What it is |
|---|---|
| `wc3gym_template` | Seeded from the prod dump, migrated to the same revision as `main`, locked against connections. Only ever copied. |
| `wc3gym_staging` | The shared staging database, same content as the template, open for connections. Every preview that adds no migration uses it. |
| `wc3gym_<branch>` | A branch's own copy of the template. Exists only while a branch that adds a migration is alive. |

The template and the shared database follow `main`: on every push to `main`, the `Vercel staging database` workflow runs `alembic upgrade head` on both, the same command the production build runs for prod. So after a merge, prod, the template and the shared database all sit at the merged revision.

## What a preview build does

`vercel.json` runs `api/preview_db.py` in every preview build. It compares the branch's latest migration with the revision `wc3gym_staging` is at:

| Situation | Action |
|---|---|
| Same revision | Use `wc3gym_staging`. Nothing is created. |
| The branch adds migrations on top of it | Copy the template to `wc3gym_<branch>` if it does not exist (`CREATE DATABASE ... TEMPLATE`, well under a second), run the branch's migrations on the copy. |
| The copy exists but the branch's migration files changed | Drop it (`WITH (FORCE)`, which disconnects the older preview) and copy the template again. |
| The branch does not know the shared database's revision (`main` moved on) | The build fails with "rebase onto main". Nothing is guessed. |
| The branch has two migration heads | The build fails. `tests/test_migrations.py` fails the same way on the pull request. |

A copy carries a sha1 of the branch's `migrations/versions` files as its database comment, written only after `alembic upgrade head` succeeds. A push that edits, renames or removes a migration in place keeps its revision id, so alembic alone would leave the copy untouched and serve a database built by the old SQL; the fingerprint catches all three.

At cold start `api/index.py` makes one lookup: if `wc3gym_<branch>` exists the preview uses it, otherwise `wc3gym_staging`. The app can only pick a database the build created.

The database name is `wc3gym_<slug>_<hash>`: the slug is the branch name lower-cased with runs of non-alphanumerics folded to `_` and cut to 16 characters, for reading; the hash is the first 8 hex digits of the sha1 of the exact branch name, so `feature/foo-bar` and `feature/foo_bar` never share a database. 32 characters at most, inside Postgres's 63-byte identifier limit. The branch name, not the pull request number, is the key: Vercel builds a branch as soon as it is pushed, which is before its pull request exists, and does not rebuild when the pull request opens.

## When a copy is removed

Exactly one trigger: GitHub reports the branch deleted. The workflow drops `wc3gym_<branch>` if it exists. There is no schedule; a database is only ever removed because its branch is gone. A branch that is kept after its pull request closes keeps its copy; `just db list vercel staging` shows it and `just db drop vercel staging <database>` removes it.

## Every case

- **Pull request without a migration.** Every push builds against the shared database. Nothing to clean up.
- **Migration pull request, closed unmerged.** The first push made a copy. Branch deleted: copy dropped. Branch kept: copy stays until the branch goes.
- **Migration pull request, merged.** Prod, template and shared database migrate to the new revision. The merged branch is deleted, its copy dropped. New branches match the shared database again and create nothing.
- **Two migration pull requests open at once.** Two copies, independent of each other.
- **One of them merges first.** The shared database moves to the merged revision; the other branch does not know it, so its next build fails with "rebase onto main". That rebase is needed anyway, or `main` would end up with two migration heads. After the rebase the branch gets a fresh copy from the now newer template.
- **Both merge and the second was never rebased.** `main` has two heads; `alembic upgrade head` refuses, so the production build fails and nothing deploys. The single-head test fails on the pull request first.
- **An old branch while `main` gained a migration.** Build fails with "rebase onto main". Stricter than needed, never a preview that silently errors.
- **A build fails halfway through a copy.** The copy is partly migrated and has no fingerprint comment. The next push drops it and copies the template again, rather than continuing on a half-migrated database.
- **A push edits a migration in place.** The revision id is unchanged, so alembic sees the copy at head, but the fingerprint differs: the copy is dropped and rebuilt.
- **Reseeding from a newer prod dump.** `just db seed vercel staging` rebuilds the template and the shared database and relocks the template. Open branch copies are untouched.

## Why a template rather than seeding each copy from scratch

Postgres refuses to copy a database that has any open connection, and the pooler always holds one on the shared database, so the shared database cannot be the copy source. The locked template is the smallest thing that can be: one extra database that nothing connects to. The alternative, creating an empty database and loading the seed repo in the build, needs a GitHub token in the Vercel build and moves the seed loader into this repo. The template needs neither; its cost is the unlock/relock around a reseed, which `just db seed vercel staging` and the workflow do.

## Why a second project rather than a second database in the production project

A Supabase project is one Postgres instance. Extra databases work through the pooler, but Studio, the auto API and the backups only see `postgres`, and the extra databases would share the production instance's CPU, disk and connection limit. The staging project keeps previews away from all of that and the free tier allows two projects.

## Pieces

| Piece | Where | Runs on |
|---|---|---|
| Choose or create the branch database, migrate it | `api/preview_db.py`, called from `vercel.json` | Preview build |
| Point the app at its database | `api/index.py` | Cold start |
| Migrate template and shared database | `.github/workflows/vercel-staging-db.yml` → `scripts/vercel_staging_db.py migrate` | Push to `main` |
| Drop a branch's copy | same workflow → `scripts/vercel_staging_db.py drop-branch <branch>` | Branch deleted |
| Single migration head | `tests/test_migrations.py` | Every pull request |
| Reseed, list, manual drop | `just db seed vercel staging`, `just db list vercel staging`, `just db drop vercel staging <database>` | By hand |

## Configuration

- Vercel project, preview environment only: `DB_URL` naming the staging project (`.../postgres`; the database part is replaced per preview), and preview-only `ADMIN_TOKEN` and `JWT_SECRET_KEY`. Production and development keep their own values.
- Repository secret `VERCEL_STAGING_DB_URL`: the same preview `DB_URL`, for the workflow.
- Vercel exposes `VERCEL_ENV` and `VERCEL_GIT_COMMIT_REF` to build and runtime (system environment variables on).
