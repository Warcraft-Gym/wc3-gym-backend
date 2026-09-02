"""Copy every stored team logo into Vercel Blob and point the row at it.

Run once per database, after the migration and before the icon column is dropped:

    DB_URL=... BLOB_READ_WRITE_TOKEN=... uv run python scripts/logos_to_blob.py [--dry-run]

Safe to run again: a team that already has an icon_url is skipped, so a half-finished run is
resumed rather than repeated. The icon column is left alone, so this is reversible until it drops.
"""

import argparse
import os
import sys

from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

from app.models.team import Team
from app.services import blob


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report, upload nothing")
    args = parser.parse_args()

    if not args.dry_run and not os.environ.get("BLOB_READ_WRITE_TOKEN"):
        sys.exit("BLOB_READ_WRITE_TOKEN is not set")

    engine = create_engine(os.environ["DB_URL"])
    moved = skipped = 0
    with Session(engine) as session:
        # undefer: this is the one job that wants the bytes
        rows = session.execute(
            select(Team.id, Team.name, Team.icon_url, Team.icon).execution_options(
                populate_existing=True
            )
        ).all()
        for team_id, name, icon_url, icon in rows:
            if icon_url:
                print(f"  {name}: already at {icon_url}")
                skipped += 1
                continue
            if not icon:
                print(f"  {name}: no logo")
                skipped += 1
                continue
            if args.dry_run:
                print(f"  {name}: would upload {len(icon)} bytes")
                moved += 1
                continue
            blob.check_icon(icon)
            url = blob.put_icon(team_id, icon)
            session.execute(update(Team).where(Team.id == team_id).values(icon_url=url))
            session.commit()
            print(f"  {name}: {len(icon)} bytes -> {url}")
            moved += 1
    print(f"{moved} moved, {skipped} skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
