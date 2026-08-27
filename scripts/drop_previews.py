"""Drop the preview databases on the staging project that no open pull request or live branch still uses.

usage: DB_URL=<staging url> python scripts/drop_previews.py <open PR numbers and branch names...>
"""

import os
import re
import sys

import psycopg

keep = set()
for arg in sys.argv[1:]:
    keep.add(
        f"wc3gym_pr{arg}"
        if arg.isdigit()
        else f"wc3gym_{re.sub(r'[^a-z0-9]+', '_', arg.lower())[:40]}"
    )
url = re.sub(
    r"/[^/?]*(\?|$)",
    r"/postgres\1",
    os.environ["DB_URL"].replace("+psycopg", ""),
    count=1,
)
with psycopg.connect(
    url, autocommit=True
) as conn:  # DROP DATABASE cannot run inside a transaction
    names = [
        r[0]
        for r in conn.execute(
            "SELECT datname FROM pg_database WHERE datname LIKE 'wc3gym_%' AND datname <> 'wc3gym_base'"
        )
    ]
    for name in names:
        if name in keep:
            continue
        conn.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
        print("dropped", name)
    print("kept", sorted(set(names) & keep))
