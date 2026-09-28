# The egress monitor's reads from a deployment: `just monitor routes staging 7` or `days=7`. Every recipe
# takes an environment first, prod by default: prod, staging (the shared preview deployment) or local (`just serve`).
# CRON_SECRET comes from .env (gitignored); prod and staging share it.

# Recipes run from the repository root, one level up from this file.
set working-directory := '..'

set shell := ["bash", "-euo", "pipefail", "-c"]
set dotenv-load

default:
    @just --list monitor

# Print the API address of an environment.
api env="prod":
    #!/usr/bin/env bash
    set -euo pipefail
    case "{{ env }}" in
    (prod)    echo "https://wc3-gym-backend-snowy.vercel.app" ;;
    (staging) echo "https://wc3-gym-backend-git-staging-wc-3-gym.vercel.app" ;;
    (local)   echo "http://localhost:5002" ;;
    (*)       echo "env must be prod, staging or local" >&2; exit 2 ;;
    esac

# What each route cost the database over the last days, most estimated egress first.
routes env="prod" days="1":
    #!/usr/bin/env bash
    set -euo pipefail
    days="{{ days }}"
    BODY=$(just monitor _get "/jobs/egress?days=${days#days=}" {{ env }})
    export BODY
    uv run python - <<'PY'
    import json, os
    from app.core.egress_stats import estimate_bytes
    rows = json.loads(os.environ["BODY"])
    for r in rows:
        r["egress_mb"] = f"{estimate_bytes(r['rows'], r['statements']) / 1e6:.1f}"
        r["response_mb"] = f"{r['bytes'] / 1e6:.1f}"
    rows.sort(key=lambda r: (r["day"], -float(r["egress_mb"])))
    columns = ("day", "method", "calls", "statements", "rows", "egress_mb", "response_mb", "route")
    table = [columns] + [tuple(str(r[c]) for c in columns) for r in rows]
    widths = [max(len(row[i]) for row in table) for i in range(len(columns) - 1)]
    for row in table:
        print("  ".join(cell.rjust(w) for cell, w in zip(row, widths)), row[-1])
    print("\negress_mb: the monitor's estimate of billed egress; response_mb: the JSON sent to the browser")
    PY

# The estimated egress between the daily snapshots of the last days, oldest first.
egress env="prod" days="7":
    #!/usr/bin/env bash
    set -euo pipefail
    days="{{ days }}"
    BODY=$(just monitor _get "/jobs/egress-snapshots?days=${days#days=}" {{ env }})
    export BODY
    uv run python - <<'PY'
    import json, os
    columns = ("start", "end", "hours", "calls", "rows", "estimated_mb", "mb_per_day", "over_budget")
    table = [columns] + [tuple(str(r[c])[:16] for c in columns) for r in json.loads(os.environ["BODY"])]
    widths = [max(len(row[i]) for row in table) for i in range(len(columns))]
    for row in table:
        print("  ".join(cell.rjust(w) for cell, w in zip(row, widths)))
    PY

# GET one job route with CRON_SECRET; a refusal names its cause instead of a traceback.
_get path env:
    #!/usr/bin/env bash
    set -euo pipefail
    api=$(just monitor api {{ env }})
    out=$(mktemp)
    trap 'rm -f "$out"' EXIT
    # The header goes through stdin so the secret never shows in a process list
    status=$(printf 'Authorization: Bearer %s\n' "${CRON_SECRET:?CRON_SECRET is not set in .env}" \
        | curl -sS --connect-timeout 5 --max-time 60 -o "$out" -w '%{http_code}' -H @- "$api{{ path }}") \
        || { echo "{{ env }} did not answer at $api" >&2; exit 1; }
    case "$status" in
    (200) cat "$out" ;;
    (401) echo "401: CRON_SECRET in .env does not match {{ env }}" >&2; exit 1 ;;
    (*)   echo "$status from $api{{ path }}" >&2; exit 1 ;;
    esac
