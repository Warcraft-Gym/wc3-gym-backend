"""Seed a migrated Postgres from a directory of CSVs (one per table, NULL as \\N), as clean-dump writes.

usage: uv run python scripts/seed_db.py <dir> <postgresql://url>

Copies every column the target table still has, keeps the ids, then sets every
sequence. FK checks are off during the copy, so table order does not matter.
"""

import ast
import csv
import io
import sys
from pathlib import Path

import psycopg

csv.field_size_limit(sys.maxsize)


def bytea(cell: str) -> str:
    """csv.writer stringified BLOBs as repr(bytes); Postgres wants hex bytea"""
    return r"\x" + ast.literal_eval(cell).hex()


def main(seed_dir: str, url: str) -> None:
    url = url.replace("postgresql+psycopg://", "postgresql://")
    files = sorted(Path(seed_dir).glob("*.csv"))
    with psycopg.connect(url, autocommit=False) as conn, conn.cursor() as cur:
        cur.execute("SET session_replication_role = replica")
        tables = [f.stem for f in files]
        cur.execute("TRUNCATE " + ", ".join(f'"{t}"' for t in tables))
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
                f"COPY \"{table}\" ({', '.join(f'"{c}"' for c in cols)}) FROM STDIN (FORMAT csv, NULL '\\N')"
            ) as copy:
                out = io.StringIO()
                w = csv.writer(out)
                for row in body:
                    vals = [row[i] for i in keep]
                    for j, c in enumerate(cols):
                        if types[c] == "bytea" and vals[j].startswith("b'"):
                            vals[j] = bytea(vals[j])
                        elif types[c] == "boolean" and vals[j] in ("0", "1"):
                            vals[j] = "false" if vals[j] == "0" else "true"
                    w.writerow(vals)
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
        cur.execute(
            "SELECT table_name, column_name FROM information_schema.columns"
            " WHERE table_schema = 'public' AND column_default LIKE 'nextval%'"
        )
        for table, col in cur.fetchall():
            cur.execute(
                f"SELECT setval(pg_get_serial_sequence('{table}', '{col}'),"
                f' COALESCE(MAX("{col}"), 0) + 1, false) FROM "{table}"'
            )
        conn.commit()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
