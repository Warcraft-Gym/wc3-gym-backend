# pg_stat_statements snapshots: which databases and statements ran most between two snapshots. Rows, not bytes:
# the measured egress per route is `just monitor routes`.
# One snapshot reads about 0.4 MB per project, so it is not for polling: twice a day at most.
# The URLs, project refs and secret keys are VERCEL_*_DB_URL and SUPABASE_* in .env (gitignored). export-ladder and push-ladder also take local (LOCAL_DB_URL).

# Recipes run from the repository root, one level up from this file.
set working-directory := '..'

set shell := ["bash", "-euo", "pipefail", "-c"]
set dotenv-load

default:
    @just --list db

# Record one snapshot per project into data/egress/ (gitignored); two are needed to report.
snapshot env="all":
    uv run python -m app.core.egress_stats snapshot {{ env }}

# Compare the last two snapshots of one project: the databases and statements that grew, in rows and calls.
report env="prod" rows="15":
    uv run python -m app.core.egress_stats report {{ env }} {{ rows }}

# Write the ladder matches and sync ledger of the players rostered in these events, or of everyone, to <dir> as CSV keyed on battle tag.
export-ladder dir env="local" *events:
    uv run python -m app.core.ladder_transfer export {{ dir }} {{ env }} {{ events }}

# Insert the rows of <dir> the target lacks, mapping each battle tag to the target's user; an unknown tag is skipped and counted.
push-ladder dir env="local":
    uv run python -m app.core.ladder_transfer push {{ dir }} {{ env }}
