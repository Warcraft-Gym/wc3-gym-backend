# The egress monitor's reads from a deployment: `just monitor routes staging 7` or `days=7`. Every recipe
# takes an environment first, prod by default: prod, staging (the preview of main) or local (`just serve`).
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
    (staging) echo "https://wc3-gym-backend-git-main-wc-3-gym.vercel.app" ;;
    (local)   echo "http://localhost:5002" ;;
    (*)       echo "env must be prod, staging or local" >&2; exit 2 ;;
    esac

# What each route's database connections received over the last days, measured, most first.
routes env="prod" days="1":
    #!/usr/bin/env bash
    set -euo pipefail
    days="{{ days }}"
    BODY=$(just monitor _get "/jobs/egress?days=${days#days=}" {{ env }})
    export BODY
    uv run python - <<'PY'
    import json, os
    rows = json.loads(os.environ["BODY"])
    for r in rows:
        r.setdefault("db_bytes", 0)
        r["db_mb"] = f"{r['db_bytes'] / 1e6:.1f}" if r["db_bytes"] or not r["statements"] else "-"
        r["response_mb"] = f"{r['bytes'] / 1e6:.1f}"
    rows.sort(key=lambda r: (r["day"], -r["db_bytes"]))
    columns = ("day", "method", "calls", "statements", "rows", "db_mb", "response_mb", "route")
    table = [columns] + [tuple(str(r[c]) for c in columns) for r in rows]
    widths = [max(len(row[i]) for row in table) for i in range(len(columns) - 1)]
    for row in table:
        print("  ".join(cell.rjust(w) for cell, w in zip(row, widths)), row[-1])
    print("\ndb_mb: bytes the database connections received (the egress); response_mb: the JSON sent")
    PY

# Each day's measured egress over the last days, oldest first.
egress env="prod" days="7":
    #!/usr/bin/env bash
    set -euo pipefail
    days="{{ days }}"
    BODY=$(just monitor _get "/jobs/egress?days=${days#days=}" {{ env }})
    export BODY
    uv run python - <<'PY'
    import json, os
    days: dict[str, list[int]] = {}
    for r in json.loads(os.environ["BODY"]):
        total = days.setdefault(r["day"], [0, 0, 0, 0, 0])
        for i, name in enumerate(("calls", "statements", "rows", "db_bytes", "bytes")):
            total[i] += r.get(name, 0)
    columns = ("day", "calls", "statements", "rows", "db_mb", "response_mb")
    table = [columns] + [
        (d, f"{c:,}", f"{s:,}", f"{n:,}", "not measured" if s and not b else f"{b / 1e6:.1f}", f"{j / 1e6:.1f}")
        for d, (c, s, n, b, j) in sorted(days.items())
    ]
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
