# The backend commands. Run them with `uv run just <recipe>`; the dev dependencies install just.
#
# One module per place the backend runs. A recipe exists in a module only if it makes sense there;
# `just <module> --list` shows what a place supports. README.md, "Where the backend runs", has the table.
# Production is EAShibby's box, reached only through Portainer, so it has no module.

set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

# The Docker stack on this machine: up, down, logs, psql, serve, alembic, seed.
mod local './just/local.just'

# The Terraform staging box, over SSH: deploy, logs, status, alembic, seed.
mod azure './just/azure.just'

# The Vercel project, prod or staging: deploy, logs, status, migrate, seed, import-maps, list, drop.
mod vercel './just/vercel.just'

alias up := local::up
alias down := local::down
alias restart := local::restart
alias logs := local::logs
alias status := local::status
alias psql := local::psql
alias serve := local::serve

# Run the tests as CI runs them. Takes pytest arguments, for example `just test -k koth`.
test *args:
    uv run pytest {{ args }}

# Check formatting and lint. CI runs this recipe too.
lint:
    uv run ruff format --check .
    uv run ruff check .

# Type-check with ty. CI runs this recipe too, as its own job.
typecheck:
    uv run ty check app tests

# What each route cost the local server's database over the last days, most rows first.
# Local only: reads GET /jobs/egress from `just serve`, with CRON_SECRET from the shell or .env.
egress-routes days="7" api="http://localhost:5002":
    #!/usr/bin/env bash
    set -euo pipefail
    secret="${CRON_SECRET:-$(grep -s '^CRON_SECRET=' .env | cut -d= -f2- || true)}"
    export LEDGER=$(curl -fsS "{{ api }}/jobs/egress?days={{ days }}" -H "Authorization: Bearer $secret")
    uv run python - <<'PY'
    import json, os
    columns = ("day", "method", "calls", "statements", "rows", "bytes", "route")
    rows = [columns] + [tuple(str(r[c]) for c in columns) for r in json.loads(os.environ["LEDGER"])]
    widths = [max(len(row[i]) for row in rows) for i in range(len(columns) - 1)]
    for row in rows:
        print("  ".join(cell.rjust(w) for cell, w in zip(row, widths)), row[-1])
    PY

# Replace the guild's slash commands with the backend's list. Reads DISCORD_APPLICATION_ID,
# DISCORD_GUILD_ID and DISCORD_BOT_TOKEN from .env; guild commands update at once.
discord-commands:
    uv run --env-file .env python -c 'from app.services.interactions import register_commands; print(register_commands())'

# Upload docs/discord-emojis/*.png as the app's emojis (race icons and the w3champions
# crown); /stats shows them once they exist. Reads DISCORD_APPLICATION_ID and DISCORD_BOT_TOKEN.
discord-emojis:
    uv run --env-file .env python -c 'from pathlib import Path; from app.services.discord import upload_app_emojis; print(upload_app_emojis(Path("docs/discord-emojis")))'

# Format the code and apply the lint fixes ruff can make.
fmt:
    uv run ruff format .
    uv run ruff check --fix .

# Clone the private seed repo into a directory. No access is not an error: the directory stays empty.
_fetch-seed dir:
    #!/usr/bin/env bash
    set -euo pipefail
    if gh repo clone Warcraft-Gym/wc3-gym-backend-db-seed "{{ dir }}" -- -q --depth 1 2>/dev/null; then
        echo "seed: $(ls "{{ dir }}"/*.csv | wc -l) tables from Warcraft-Gym/wc3-gym-backend-db-seed"
    else
        echo "seed: no access to Warcraft-Gym/wc3-gym-backend-db-seed, the database stays empty" >&2
    fi

# Load a seed directory, then push its logos/<team id>.<ext> through the upload path, so the database
# owns its blobs and a replaced production logo cannot break it. No token: teams keep the default logo.
_load-seed dir url:
    #!/usr/bin/env bash
    set -euo pipefail
    export DB_URL="{{ url }}"
    # the URLs the load is about to drop; deleted last, so a failed upload leaves an orphan, not a broken image
    previous=$(uv run python -c 'from sqlalchemy import text; from app.core.db import Session, init_engine; init_engine(); print(*[u for (u,) in Session().execute(text("SELECT icon_url FROM teams WHERE icon_url IS NOT NULL"))])')
    uv run python -m app.core.seed "{{ dir }}" "$DB_URL"
    if [ -z "${BLOB_READ_WRITE_TOKEN:-}" ]; then echo "logos: BLOB_READ_WRITE_TOKEN is not set, teams keep the default logo" >&2; exit 0; fi
    uv run python - "{{ dir }}/logos" $previous <<'PY'
    import sys
    from pathlib import Path
    from app.api.deps import team_service
    from app.core.db import init_engine
    from app.services import blob
    init_engine()
    logos = sorted(Path(sys.argv[1]).glob("*.*")) if Path(sys.argv[1]).is_dir() else []
    for file in logos:
        team_service.update_icon(int(file.stem), file.read_bytes())
    for url in sys.argv[2:]:
        blob.delete_icon(url)
    print(f"logos: {len(logos)} uploaded, {len(sys.argv) - 2} replaced")
    PY

# Regenerate docs/okf/index.html, the graph viewer that GitHub Pages serves. Node colours per concept type.
okf-graph:
    #!/usr/bin/env bash
    set -euo pipefail
    rm -rf /tmp/okf-spec && git clone -q --depth 1 https://github.com/GoogleCloudPlatform/open-knowledge-format /tmp/okf-spec
    PYTHONPATH=/tmp/okf-spec/src uv run --no-project --with pyyaml python - <<'EOF'
    import re
    from pathlib import Path
    import reference_agent.viewer.generator as G
    G._TYPE_PALETTE.clear()
    G._TYPE_PALETTE.update({"Domain Concept": "#2a78d6", "Decision": "#eb6834", "Runbook": "#1baf7a", "Convention": "#eda100", "Integration": "#e87ba4", "Data Model": "#008300", "API Area": "#4a3aa7", "Pitfall": "#e34948"})
    walk = G._walk_concepts
    def rooted(bundle_root):
        # The viewer rewires only bundle-rooted links (/a/b.md); the bundle writes relative ones.
        concepts = walk(bundle_root)
        for c in concepts:
            here = Path(c.id).parent
            c.body = re.sub(r"\]\((?!https?://|/|#)([^)\s]+\.md)(#[^)]*)?\)", lambda m: "](/" + (here / m.group(1)).resolve().relative_to(Path.cwd()).as_posix() + (m.group(2) or "") + ")" if (here / m.group(1)).resolve().is_relative_to(Path.cwd()) else m.group(0), c.body)
        return concepts
    G._walk_concepts = rooted
    print(G.generate_visualization(Path("docs/okf"), Path("docs/okf/index.html"), bundle_name="wc3-gym-backend knowledge bundle"))
    EOF
    sed -i 's#<head>#<head>\n  <meta name="robots" content="noindex, nofollow">#' docs/okf/index.html

# Check docs/okf against OKF v0.2 with a third-party validator, the okf crate. Installs it once.
okf-validate:
    command -v okf >/dev/null || cargo install okf
    okf validate docs/okf

# List the concepts whose source files changed after the concept was written: the review list behind AGENTS.md rule 3.
okf-drift:
    #!/usr/bin/env -S uv run --no-project python
    import re, subprocess, pathlib
    from datetime import datetime
    for p in sorted(pathlib.Path("docs/okf").rglob("*.md")):
        if p.name in ("index.md", "log.md"): continue
        fm = p.read_text().split("\n---\n", 1)[0]
        at = re.search(r"generated: \{.*?at: (\S+?) ?\}", fm)
        if not at: continue
        written = datetime.fromisoformat(at.group(1).replace("Z", "+00:00"))
        for src in re.findall(r"^\s+resource: (\.\S+)$", fm, re.M):
            f = (p.parent / src).resolve()
            stamp = subprocess.run(["git", "log", "-1", "--format=%cI", "--", f], capture_output=True, text=True).stdout.strip()
            if stamp and datetime.fromisoformat(stamp) > written:
                print(f"{p}  <-  {f.relative_to(pathlib.Path.cwd())} changed {stamp[:10]}")

# Stamp the table concepts machine-verified once test_okf proves each Schema against the models; the spec's process tier.
okf-verify:
    #!/usr/bin/env -S uv run python
    import re, subprocess, sys, pathlib
    from datetime import datetime, timezone
    if subprocess.run(["uv", "run", "pytest", "tests/test_okf.py", "-q", "-k", "table"]).returncode:
        sys.exit(1)
    stamp = "{ by: process:test_okf, at: " + datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") + " }"
    for p in sorted(pathlib.Path("docs/okf/data/tables").glob("*.md")):
        if p.name == "index.md": continue
        t = p.read_text()
        if re.search(r"^verified: \{ by: process:test_okf", t, re.M):
            t = re.sub(r"^verified: \{ by: process:test_okf.*$", "verified: " + stamp, t, count=1, flags=re.M)
        elif re.search(r"^  - \{ by: process:test_okf", t, re.M):
            t = re.sub(r"^  - \{ by: process:test_okf.*$", "  - " + stamp, t, count=1, flags=re.M)
        elif re.search(r"^verified:\n", t, re.M):
            t = re.sub(r"^verified:\n", "verified:\n  - " + stamp + "\n", t, count=1, flags=re.M)
        elif re.search(r"^verified: \{", t, re.M):
            t = re.sub(r"^verified: (\{.*\})$", "verified:\n  - \\1\n  - " + stamp, t, count=1, flags=re.M)
        else:
            t = re.sub(r"^(generated: .*)$", "\\1\nverified: " + stamp, t, count=1, flags=re.M)
        p.write_text(t)
    print("stamped every table concept")
