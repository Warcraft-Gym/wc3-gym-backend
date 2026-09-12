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
from typing import Any, LiteralString

import psycopg
from psycopg import sql

from app.core.achievements import WC3NO_PAID

csv.field_size_limit(sys.maxsize)

# The seed repo still names the dumps after the old tables
RENAMED = {"seasons": "event", "user_season_availability": "round_availability"}
# The dump predates the rounds, so the round ids are filled after the copy
RELAX = (
    "ALTER TABLE matches ALTER COLUMN round_id DROP NOT NULL",
    "ALTER TABLE series ALTER COLUMN round_id DROP NOT NULL",
    "ALTER TABLE round_availability DROP CONSTRAINT pk_round_availability",
    "ALTER TABLE round_availability ALTER COLUMN round_id DROP NOT NULL",
)
RESTORE = (
    "ALTER TABLE matches ALTER COLUMN round_id SET NOT NULL",
    "ALTER TABLE series ALTER COLUMN round_id SET NOT NULL",
    "ALTER TABLE round_availability ALTER COLUMN round_id SET NOT NULL",
    (
        "ALTER TABLE round_availability ADD CONSTRAINT pk_round_availability"
        " PRIMARY KEY (user_id, round_id)"
    ),
)
KOTH_LEAGUE = "Gym KOTH"


def convert(cell: str, data_type: str) -> str:
    """The two cells COPY cannot take as written: repr(bytes) BLOBs and MySQL 0/1 booleans"""
    if data_type == "bytea" and cell.startswith("b'"):
        return r"\x" + ast.literal_eval(cell).hex()
    if data_type == "boolean" and cell in ("0", "1"):
        return "true" if cell == "1" else "false"
    return cell


def scalar(
    cur: psycopg.Cursor,
    statement: LiteralString,
    params: tuple[Any, ...] = (),
) -> Any:  # noqa: ANN401  # any column type
    """The first column of the first row, or None."""
    cur.execute(statement, params)
    row = cur.fetchone()
    return row[0] if row else None


def koth_rounds(cur: psycopg.Cursor) -> None:
    """The KOTH half of 96c0d36de81c: the truncate takes the event and its nights.

    The dump brings the koth_events rows back, so the event, its stage and one
    round per night are made again and each night points at its round. The
    league row survives the truncate, so the event hangs off the one there.
    """
    cur.execute("SELECT id, name, event_date FROM koth_events ORDER BY event_date, id")
    nights = cur.fetchall()
    if not nights:
        return
    cur.execute(
        "INSERT INTO league (name, short_name, entrant_kind)"
        " VALUES (%s, 'KOTH', 'solo') ON CONFLICT (name) DO NOTHING",
        (KOTH_LEAGUE,),
    )
    league_id = scalar(cur, "SELECT id FROM league WHERE name = %s", (KOTH_LEAGUE,))
    # Signups closed: KOTH takes its entrants in Twitch chat, not on the member home
    event_id = scalar(
        cur,
        "INSERT INTO event (name, series_per_round, kind, published, signups_open,"
        " league_id) VALUES (%s, 1, 'koth', TRUE, FALSE, %s) RETURNING id",
        (KOTH_LEAGUE, league_id),
    )
    stage_id = scalar(
        cur,
        "INSERT INTO event_stage (event_id, position, format, best_of,"
        " scheduling_mode) VALUES (%s, 1, 'koth', 1, 'immediate') RETURNING id",
        (event_id,),
    )
    for number, (koth_id, name, event_date) in enumerate(nights, start=1):
        day = event_date.date()
        round_id = scalar(
            cur,
            "INSERT INTO event_round (season_id, stage_id, number, name, start_date,"
            " end_date, best_of) VALUES (%s, %s, %s, %s, %s, %s, 1) RETURNING id",
            (event_id, stage_id, number, name, day, day),
        )
        cur.execute(
            "UPDATE koth_events SET round_id = %s WHERE id = %s", (round_id, koth_id)
        )


def main(seed_dir: str, url: str) -> None:
    url = url.replace("postgresql+psycopg://", "postgresql://")
    files = sorted(Path(seed_dir).glob("*.csv"))
    with psycopg.connect(url, autocommit=False) as conn, conn.cursor() as cur:
        cur.execute("SET session_replication_role = replica")
        for statement in RELAX:
            cur.execute(statement)
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
        cur.execute(
            "UPDATE event SET score_system = 'helpstone'"
        )  # MySQL kept it in settings, one value for every season
        # The dump predates the rename, so the copied events carry no league and
        # the CASCADE took their stages: redo the two backfills of 1e0287eacccf
        cur.execute(
            "UPDATE event SET league_id = (SELECT id FROM league WHERE name = 'GNL')"
            " WHERE league_id IS NULL"
        )
        cur.execute(
            "INSERT INTO event_stage (event_id, position, format, best_of, map_rules,"
            " scheduling_mode, ranking_rule, points_series_won, points_series_drawn,"
            " points_game_won) SELECT id, 1, 'round_robin', 3, map_rules, 'agreed',"
            " 'points,game_diff,head_to_head', 1, 0, 0 FROM event e WHERE NOT EXISTS"
            " (SELECT 1 FROM event_stage s WHERE s.event_id = e.id)"
        )
        # The CASCADE took the rounds too, and the dump predates them: one round
        # per playday a match or an answer names, then the round ids the matches,
        # the series and the answers carry (the backfills of 96c0d36de81c)
        cur.execute(
            "INSERT INTO event_round (season_id, stage_id, number)"
            " SELECT DISTINCT p.season_id, s.id, p.number FROM"
            " (SELECT season_id, playday AS number FROM matches"
            " UNION SELECT season_id, playday FROM round_availability) p"
            " LEFT JOIN event_stage s ON s.event_id = p.season_id AND s.position = 1"
            " WHERE NOT EXISTS (SELECT 1 FROM event_round r"
            " WHERE r.season_id = p.season_id AND r.number = p.number)"
        )
        cur.execute(
            "UPDATE matches SET round_id = (SELECT r.id FROM event_round r"
            " WHERE r.season_id = matches.season_id AND r.number = matches.playday)"
        )
        cur.execute(
            "UPDATE series SET round_id ="
            " (SELECT m.round_id FROM matches m WHERE m.id = series.match_id)"
        )
        cur.execute(
            "UPDATE round_availability SET round_id = (SELECT r.id FROM event_round r"
            " WHERE r.season_id = round_availability.season_id"
            " AND r.number = round_availability.playday)"
        )
        for statement in RESTORE:
            cur.execute(statement)
        # The prices went with the CASCADE. Every season in the dump ran under
        # wc3.no, so each gets those exact rows; a season made in the app takes
        # DEFAULT_PAID at creation instead.
        cur.executemany(
            "INSERT INTO ladder_achievements (season_id, rule_id, points)"
            " SELECT id, %s, %s FROM event",
            list(WC3NO_PAID.items()),
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
        # After the sequences: the new event takes an id the copied rows do not hold
        koth_rounds(cur)
        conn.commit()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
