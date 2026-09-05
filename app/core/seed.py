"""Seed a migrated Postgres from a directory of CSVs (one per table, NULL as \\N), as the seed repo holds them.

usage: uv run python -m app.core.seed <dir> <postgresql://url>

Copies every column the target table still has, keeps the ids, then sets every
sequence. FK checks are off during the copy, so table order does not matter.
The seeded seasons get the achievement catalogue at catalogue prices.
"""

import ast
import csv
import io
import sys
from pathlib import Path

import psycopg
from psycopg import sql

from app.core.achievements import DEFAULT_PAID

csv.field_size_limit(sys.maxsize)


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
    with psycopg.connect(url, autocommit=False) as conn, conn.cursor() as cur:
        cur.execute("SET session_replication_role = replica")
        tables = [f.stem for f in files]
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
        cur.execute(
            "UPDATE seasons SET score_system = 'helpstone'"
        )  # MySQL kept it in settings, one value for every season
        cur.executemany(  # the prices the migration seeded went with the CASCADE
            "INSERT INTO ladder_achievements (season_id, rule_id, points)"
            " SELECT id, %s, %s FROM seasons",
            list(DEFAULT_PAID.items()),
        )
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
        conn.commit()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
