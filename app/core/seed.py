"""Seed a migrated Postgres from a directory of CSVs (one per table, NULL as \\N), as the seed repo holds them.

usage: uv run python -m app.core.seed <dir> <postgresql://url>
       uv run python -m app.core.seed export <dir> <postgresql://url>

The load copies every column the target table still has, keeps the ids, then
sets every sequence. FK checks are off during the copy, so table order does not
matter. A directory with a `manifest.json` is a snapshot the export wrote: the
database must sit at the manifest's alembic revision, and the rows load as they
are. A directory without one predates the event model, and the load rebuilds
the leagues, stages, rounds and catalogue prices its CSVs lack.

The export writes one CSV per table, ordered by primary key, blanks the secret
settings, and records the alembic revision in `manifest.json`.
"""

import ast
import csv
import io
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg import sql

from app.core.achievements import WC3NO_PAID

csv.field_size_limit(sys.maxsize)

# The seed repo still names the dump after the old table, and `seasons` is now a view
RENAMED = {"seasons": "event"}
# Settings whose value never leaves the database
SECRET_SETTINGS = frozenset({"KOTH_NIGHTBOT_TOKEN"})


def blank_secrets(table: str, header: list[str], row: list[str]) -> list[str]:
    """The row as the export writes it: a secret setting keeps its key and loses its value"""
    if table != "settings" or "key" not in header or "value" not in header:
        return row
    if row[header.index("key")] in SECRET_SETTINGS:
        row = list(row)
        row[header.index("value")] = ""
    return row


def convert(cell: str, data_type: str) -> str:
    """The two cells COPY cannot take as written: repr(bytes) BLOBs and MySQL 0/1 booleans"""
    if data_type == "bytea" and cell.startswith("b'"):
        return r"\x" + ast.literal_eval(cell).hex()
    if data_type == "boolean" and cell in ("0", "1"):
        return "true" if cell == "1" else "false"
    return cell


def main(seed_dir: str, url: str) -> None:
    url = url.replace("postgresql+psycopg://", "postgresql://")
    files = sorted(Path(seed_dir).glob("*.csv"))
    manifest_path = Path(seed_dir) / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    with psycopg.connect(url, autocommit=False) as conn, conn.cursor() as cur:
        if manifest:
            cur.execute("SELECT version_num FROM alembic_version")
            at = cur.fetchone()
            if not at or at[0] != manifest["alembic_revision"]:
                raise SystemExit(
                    f"the database is at {at[0] if at else 'no revision'},"
                    f" the seed needs {manifest['alembic_revision']}"
                )
        cur.execute("SET session_replication_role = replica")
        tables = [RENAMED.get(f.stem, f.stem) for f in files]
        # CASCADE: tables outside the seed set reference these (ladder_achievements,
        # ladder_sync, w3c_ladder_matches, team_season_captain, discord_role_binding)
        cur.execute(
            sql.SQL("TRUNCATE {} CASCADE").format(
                sql.SQL(", ").join(map(sql.Identifier, tables))
            )
        )
        for table, path in zip(tables, files):
            rows = list(csv.reader(path.open(encoding="utf-8")))
            header, body = rows[0], rows[1:]
            cur.execute(
                "SELECT column_name, data_type FROM information_schema.columns"
                " WHERE table_name = %s AND is_generated = 'NEVER'",
                (table,),
            )
            types = dict(cur.fetchall())
            keep = [i for i, c in enumerate(header) if c in types]
            cols = [header[i] for i in keep]
            with cur.copy(
                sql.SQL("COPY {} ({}) FROM STDIN (FORMAT csv, NULL '\\N')").format(
                    sql.Identifier(table),
                    sql.SQL(", ").join(map(sql.Identifier, cols)),
                )
            ) as copy:
                out = io.StringIO()
                w = csv.writer(out)
                for row in body:
                    w.writerow([convert(row[i], types[c]) for i, c in zip(keep, cols)])
                copy.write(out.getvalue())
            dropped = sorted(set(header) - set(cols))
            print(
                f"{table}: {len(body)} rows"
                + (f", skipped {dropped}" if dropped else "")
            )
        cur.execute("SET session_replication_role = DEFAULT")
        # Before the backfills, so their new rows never take an id a CSV row holds
        cur.execute(
            "SELECT table_name, column_name FROM information_schema.columns"
            " WHERE table_schema = 'public' AND column_default LIKE 'nextval%'"
        )
        for table, col in cur.fetchall():
            cur.execute(
                sql.SQL(
                    "SELECT setval(pg_get_serial_sequence({}, {}),"
                    " COALESCE(MAX({}), 0) + 1, false) FROM {}"
                ).format(
                    sql.Literal(table),
                    sql.Literal(col),
                    sql.Identifier(col),
                    sql.Identifier(table),
                )
            )
        if manifest is None:
            _rebuild_event_rows(cur)
        conn.commit()


def _rebuild_event_rows(cur: psycopg.Cursor) -> None:
    """What a snapshot from before the event model lacks: the GNL score system, the
    league, one stage and its rounds per season, and the catalogue prices."""
    cur.execute(
        "UPDATE event SET score_system = 'helpstone' WHERE kind = 'gnl'"
    )  # MySQL kept it in settings, one value for every GNL season
    # The dump predates the rename, so the copied events carry no league and
    # the CASCADE took their stages: redo the two backfills of 1e0287eacccf
    cur.execute(
        "UPDATE event SET league_id ="
        " (SELECT id FROM league WHERE short_name = 'GNL') WHERE league_id IS NULL"
    )
    cur.execute(
        "INSERT INTO event_stage (event_id, position, format, best_of, map_rules,"
        " scheduling_mode, ranking_rule, points_series_won, points_series_drawn,"
        " points_game_won) SELECT id, 1, 'round_robin', 3, map_rules, 'agreed',"
        " 'points,game_diff,head_to_head', 1, 0, 0 FROM event e WHERE NOT EXISTS"
        " (SELECT 1 FROM event_stage s WHERE s.event_id = e.id)"
    )
    # The CASCADE took the rounds too, and the dump predates them: one round
    # per playday the matches name, then the round ids the matches and the
    # series carry (the backfills of 96c0d36de81c)
    cur.execute(
        "INSERT INTO event_round (season_id, stage_id, number)"
        " SELECT DISTINCT m.season_id, s.id, m.playday FROM matches m"
        " LEFT JOIN event_stage s ON s.event_id = m.season_id AND s.position = 1"
        " WHERE NOT EXISTS (SELECT 1 FROM event_round r"
        " WHERE r.season_id = m.season_id AND r.number = m.playday)"
    )
    cur.execute(
        "UPDATE matches SET round_id = (SELECT r.id FROM event_round r"
        " WHERE r.season_id = matches.season_id AND r.number = matches.playday)"
    )
    cur.execute(
        "UPDATE series SET round_id ="
        " (SELECT m.round_id FROM matches m WHERE m.id = series.match_id)"
    )
    # The prices went with the CASCADE. Every GNL season in the dump ran
    # under wc3.no, so each gets those exact rows; a KOTH night has none,
    # and a season made in the app takes DEFAULT_PAID at creation instead.
    cur.executemany(
        "INSERT INTO ladder_achievements (season_id, rule_id, points)"
        " SELECT id, %s, %s FROM event WHERE kind = 'gnl'",
        list(WC3NO_PAID.items()),
    )


def export(seed_dir: str, url: str) -> None:
    """Write one CSV per table of the database into the directory, plus `manifest.json`.

    Rows sort by primary key so a refresh diffs cleanly. Views and `alembic_version`
    stay out; the manifest carries the revision instead.
    """
    url = url.replace("postgresql+psycopg://", "postgresql://")
    out = Path(seed_dir)
    out.mkdir(parents=True, exist_ok=True)
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT version_num FROM alembic_version")
        revision = cur.fetchone()[0]
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
            " AND table_type = 'BASE TABLE' AND table_name <> 'alembic_version' ORDER BY 1"
        )
        tables = [name for (name,) in cur.fetchall()]
        for table in tables:
            cur.execute(
                "SELECT a.attname FROM pg_index i JOIN pg_attribute a"
                " ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)"
                " WHERE i.indrelid = %s::regclass AND i.indisprimary ORDER BY a.attnum",
                (table,),
            )
            keys = [name for (name,) in cur.fetchall()] or ["1"]
            order = sql.SQL(", ").join(
                sql.Identifier(k) if k != "1" else sql.SQL("1") for k in keys
            )
            raw = io.BytesIO()
            with cur.copy(
                sql.SQL(
                    "COPY (SELECT * FROM {} ORDER BY {}) TO STDOUT"
                    " (FORMAT csv, HEADER, NULL '\\N')"
                ).format(sql.Identifier(table), order)
            ) as copy:
                for chunk in copy:
                    raw.write(bytes(chunk))
            rows = list(csv.reader(io.StringIO(raw.getvalue().decode("utf-8"))))
            header, body = rows[0], rows[1:]
            with (out / f"{table}.csv").open("w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(header)
                w.writerows(blank_secrets(table, header, row) for row in body)
            print(f"{table}: {len(body)} rows")
    (out / "manifest.json").write_text(
        json.dumps(
            {
                "alembic_revision": revision,
                "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "tables": tables,
                "excluded": ["alembic_version"],
                "blanked_settings": sorted(SECRET_SETTINGS),
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    if sys.argv[1] == "export":
        export(sys.argv[2], sys.argv[3])
    else:
        main(sys.argv[1], sys.argv[2])
