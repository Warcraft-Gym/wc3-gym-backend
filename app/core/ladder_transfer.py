"""Copy W3Champions ladder rows from one database to another.

A backfill read on the local stack goes to production as two CSV files, so it
costs no Vercel compute and no cron walk. User ids differ between databases,
so the files carry the battle tag, and the load maps it to the target's user.

usage: uv run python -m app.core.ladder_transfer export <dir> <env> [event ids...]
       uv run python -m app.core.ladder_transfer push <dir> <env>

<env> is local, staging or prod; `just db` loads the URLs from .env. The push
reads the id and tag of every target user once, then writes; it returns no rows.
"""

import csv
import os
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import Executable, and_, case, not_, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core.db import Session, init_engine
from app.models.ladder_sync import LadderSync, LadderSyncBase
from app.models.user import User
from app.models.user_battle_tag import UserBattleTag
from app.models.user_team_season import DBUserTeamSeason
from app.models.w3c_ladder_match import W3CLadderMatch, W3CLadderMatchBase

URLS = {
    "local": "LOCAL_DB_URL",
    "staging": "VERCEL_STAGING_DB_URL",
    "prod": "VERCEL_PROD_DB_URL",
}
# The file, its table, the fields it carries and the unique key a repeat hits
TABLES: list[tuple[str, type[W3CLadderMatch | LadderSync], list[str], list[str]]] = [
    (
        "w3c_ladder_matches.csv",
        W3CLadderMatch,
        list(W3CLadderMatchBase.model_fields),
        ["w3c_match_id", "user_id"],
    ),
    (
        "ladder_sync.csv",
        LadderSync,
        [f for f in LadderSyncBase.model_fields if f != "user_id"],
        ["user_id", "wc3_season"],
    ),
]
CHUNK = 1_000


def _tag(tag: str) -> str:
    """The form the unique index on users compares."""
    return tag.strip().lower()


def export(session: OrmSession, out: Path, event_ids: list[int]) -> dict[str, int]:
    """Write both files for the players rostered in these events, or for everyone."""
    out.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name, model, fields, _ in TABLES:
        query = (
            select(model, col(User.battleTag))
            .join(User, col(User.id) == col(model.user_id))
            .order_by(col(model.id))
        )
        if event_ids:
            query = query.where(
                col(model.user_id).in_(
                    select(col(DBUserTeamSeason.user_id)).where(
                        col(DBUserTeamSeason.season_id).in_(event_ids)
                    )
                )
            )
        # ponytail: holds one table in memory; fine to a few million rows
        rows = session.execute(query).all()
        with (out / name).open("w", newline="") as f:
            writer = csv.DictWriter(f, ["battle_tag", *fields])
            writer.writeheader()
            for row, tag in rows:
                writer.writerow(
                    {"battle_tag": tag}
                    | row.model_dump(mode="json", include=set(fields))
                )
        counts[name] = len(rows)
    return counts


def _newer(insert: Any, values: list[dict[str, Any]]) -> Executable:  # noqa: ANN401
    """Move each ledger row the target holds to what either side knows: the later
    stamp, complete when either read the season to its end, the earlier read_from.
    A row that would not change is left alone, so the count is rows changed."""
    stmt = insert(LadderSync).values(values)
    new = stmt.excluded
    synced, done, since = (
        col(LadderSync.synced_at),
        col(LadderSync.complete),
        col(LadderSync.read_from),
    )
    later = new.synced_at > synced
    earlier = or_(
        and_(since.is_(None), new.read_from.is_not(None)), new.read_from < since
    )
    return stmt.on_conflict_do_update(
        index_elements=["user_id", "wc3_season"],
        set_={
            "synced_at": case((later, new.synced_at), else_=synced),
            "complete": or_(done, new.complete),
            "read_from": case((earlier, new.read_from), else_=since),
        },
        where=or_(later, and_(new.complete, not_(done)), earlier),
    )


def _count(session: OrmSession, stmt: Executable) -> int:
    # psycopg reports -1 for a multi-row insert unless asked to keep the count
    result = session.execute(stmt, execution_options={"preserve_rowcount": True})
    return result.rowcount  # ty: ignore[unresolved-attribute]


def push(session: OrmSession, source: Path) -> dict[str, tuple[int, int, int, int]]:
    """Insert the rows the target lacks and bring its ledger rows up to date:
    rows read, inserted, updated and skipped per file."""
    missing = [name for name, *_ in TABLES if not (source / name).is_file()]
    if missing:
        raise FileNotFoundError(f"{source} lacks {', '.join(missing)}")
    # any tag the person holds finds them, not only the active one
    users = {
        _tag(tag): uid
        for uid, tag in session.execute(
            select(col(UserBattleTag.user_id), col(UserBattleTag.tag))
        )
    }
    insert = (
        pg_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
    )
    counts = {}
    for name, model, _, key in TABLES:
        base = W3CLadderMatchBase if model is W3CLadderMatch else LadderSyncBase
        read, values = 0, []
        with (source / name).open(newline="") as f:
            for raw in csv.DictReader(f):
                read += 1
                user_id = users.get(_tag(raw.pop("battle_tag")))
                if user_id is None:
                    continue
                # csv writes None as an empty cell
                data: dict[str, Any] = {k: v or None for k, v in raw.items()}
                values.append(
                    base.model_validate(data | {"user_id": user_id}).model_dump()
                    | {"user_id": user_id}
                )
        inserted = updated = 0
        # ponytail: copies _write_matches, share a helper when a third caller appears
        for start in range(0, len(values), CHUNK):
            chunk = values[start : start + CHUNK]
            inserted += _count(
                session,
                insert(model).values(chunk).on_conflict_do_nothing(index_elements=key),
            )
            # Every row of the chunk now exists, so this one only updates
            if model is LadderSync:
                updated += _count(session, _newer(insert, chunk))
        counts[name] = (read, inserted, updated, read - len(values))
    return counts


def main() -> None:
    action, source, env, *events = sys.argv[1:]
    if env not in URLS:
        sys.exit(f"env must be one of {', '.join(URLS)}")
    url = os.environ.get(URLS[env])
    if not url:
        sys.exit(f"{URLS[env]} is not set")
    init_engine(url)
    path = Path(source)
    with Session.begin() as session:
        if action == "export":
            for name, rows in export(session, path, [int(e) for e in events]).items():
                print(f"{name}: {rows:,} rows")
        else:
            try:
                counts = push(session, path)
            except FileNotFoundError as err:
                sys.exit(str(err))
            for name, (read, inserted, updated, skipped) in counts.items():
                print(
                    f"{name}: read {read:,}, inserted {inserted:,}, updated {updated:,},"
                    f" skipped {skipped:,} for an unknown tag"
                )


if __name__ == "__main__":
    main()
