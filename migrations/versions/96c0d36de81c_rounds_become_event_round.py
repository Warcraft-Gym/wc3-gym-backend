"""Rounds become event round

The third of the four deploys of the events model. `season_rounds` becomes
`event_round`: it gains an id, a stage, a name and a best-of override, and
`playday` is spelled `number`. A `season_rounds` view stands in for the old
name while the running deploy still reads it, and the same is done for
`user_season_availability`, which becomes `round_availability`.

Matches, series and availability answers each gain a nullable `round_id`,
filled here; C2 refuses a null on them. Every match keyed on a playday with
no round row gets one, so no series is left without a parent.

KOTH joins the model: a "Gym KOTH" league holds one running event with one
koth stage, each existing `koth_events` row becomes one round of it, and
`koth_events.round_id` names that round, keyed to clear if the round goes.

Revision ID: 96c0d36de81c
Revises: 8cc6dd6d93eb
Create Date: 2026-09-12 05:40:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "96c0d36de81c"
down_revision: str | Sequence[str] | None = "8cc6dd6d93eb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KOTH_LEAGUE = "Gym KOTH"
ROUNDS_VIEW = (
    "CREATE VIEW season_rounds AS SELECT season_id, number AS playday, "
    "start_date, end_date, map_id FROM event_round"
)
AVAILABILITY_VIEW = (
    "CREATE VIEW user_season_availability AS SELECT user_id, season_id, playday, "
    "available, set_by_user_id FROM round_availability"
)


def add_round_id(table: str, ondelete: str | None = None) -> None:
    """A nullable round_id with its foreign key and index, on either dialect.

    SQLite reads an ON DELETE back only off a table-level key, so a key that
    carries one rebuilds the table; a plain key rides on the column it adds.
    """
    name = op.f(f"fk_{table}_round_id_event_round")
    column = sa.Column("round_id", sa.Integer(), nullable=True)
    if op.get_bind().dialect.name == "sqlite" and not ondelete:
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN round_id INTEGER "
            "REFERENCES event_round (id)"
        )
    elif op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(table) as batch:
            batch.add_column(column)
            batch.create_foreign_key(
                name, "event_round", ["round_id"], ["id"], ondelete=ondelete
            )
    else:
        op.add_column(table, column)
        op.create_foreign_key(
            name, table, "event_round", ["round_id"], ["id"], ondelete=ondelete
        )
    op.create_index(op.f(f"ix_{table}_round_id"), table, ["round_id"])


def drop_round_id(table: str, rebuild: bool = False) -> None:
    """Undo add_round_id. SQLite drops no column a table-level key names, so
    the table add_round_id rebuilt is rebuilt again without it."""
    name = op.f(f"fk_{table}_round_id_event_round")
    op.drop_index(op.f(f"ix_{table}_round_id"), table_name=table)
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint(name, table, type_="foreignkey")
        op.drop_column(table, "round_id")
    elif rebuild:
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(name, type_="foreignkey")
            batch.drop_column("round_id")
    else:
        op.drop_column(table, "round_id")


def koth_rounds() -> None:
    """One round per KOTH night, under one running event of the KOTH league."""
    bind = op.get_bind()
    nights = bind.execute(
        sa.text("SELECT id, name, event_date FROM koth_events ORDER BY event_date, id")
    ).all()
    if not nights:
        return
    league_id = bind.scalar(
        sa.text(
            "INSERT INTO league (name, short_name, entrant_kind) "
            "VALUES (:name, 'KOTH', 'solo') RETURNING id"
        ),
        {"name": KOTH_LEAGUE},
    )
    # Signups closed: KOTH takes its entrants in Twitch chat, not on the member home
    event_id = bind.scalar(
        sa.text(
            "INSERT INTO event (name, series_per_round, kind, published, "
            "signups_open, league_id) "
            "VALUES (:name, 1, 'koth', TRUE, FALSE, :league_id) RETURNING id"
        ),
        {"name": KOTH_LEAGUE, "league_id": league_id},
    )
    stage_id = bind.scalar(
        sa.text(
            "INSERT INTO event_stage (event_id, position, format, best_of, "
            "scheduling_mode) VALUES (:event_id, 1, 'koth', 1, 'immediate') "
            "RETURNING id"
        ),
        {"event_id": event_id},
    )
    for number, (koth_id, name, event_date) in enumerate(nights, start=1):
        day = event_date.date() if hasattr(event_date, "date") else str(event_date)[:10]
        round_id = bind.scalar(
            sa.text(
                "INSERT INTO event_round (season_id, stage_id, number, name, "
                "start_date, end_date, best_of) "
                "VALUES (:event_id, :stage_id, :number, :name, :day, :day, 1) "
                "RETURNING id"
            ),
            {
                "event_id": event_id,
                "stage_id": stage_id,
                "number": number,
                "name": name,
                "day": day,
            },
        )
        bind.execute(
            sa.text("UPDATE koth_events SET round_id = :round_id WHERE id = :koth_id"),
            {"round_id": round_id, "koth_id": koth_id},
        )


def upgrade() -> None:
    op.create_table(
        "event_round",
        sa.Column("id", sa.Integer(), nullable=False),
        # Null while the season_rounds view still takes inserts; C2 refuses a null
        sa.Column("stage_id", sa.Integer(), nullable=True),
        sa.Column("season_id", sa.Integer(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("map_id", sa.Integer(), nullable=True),
        sa.Column("best_of", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["stage_id"],
            ["event_stage.id"],
            name=op.f("fk_event_round_stage_id_event_stage"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["season_id"], ["event.id"], name=op.f("fk_event_round_season_id_event")
        ),
        sa.ForeignKeyConstraint(
            ["map_id"],
            ["maps.id"],
            name=op.f("fk_event_round_map_id_maps"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event_round")),
        # The key the rounds were stored under before the id
        sa.UniqueConstraint(
            "season_id", "number", name=op.f("uq_event_round_season_id_number")
        ),
    )
    op.create_index(op.f("ix_event_round_stage_id"), "event_round", ["stage_id"])
    op.create_index(op.f("ix_event_round_map_id"), "event_round", ["map_id"])

    # Every season has one stage from B1, so every round of it hangs off that one
    op.execute(
        "INSERT INTO event_round (season_id, stage_id, number, start_date, end_date, "
        "map_id) SELECT r.season_id, s.id, r.playday, r.start_date, r.end_date, "
        "r.map_id FROM season_rounds r LEFT JOIN event_stage s "
        "ON s.event_id = r.season_id AND s.position = 1"
    )
    # A match names a playday with no round row of its own on older seasons
    op.execute(
        "INSERT INTO event_round (season_id, stage_id, number) "
        "SELECT DISTINCT m.season_id, s.id, m.playday FROM matches m "
        "LEFT JOIN event_stage s ON s.event_id = m.season_id AND s.position = 1 "
        "WHERE NOT EXISTS (SELECT 1 FROM event_round r "
        "WHERE r.season_id = m.season_id AND r.number = m.playday)"
    )
    op.drop_index(op.f("ix_season_rounds_map_id"), table_name="season_rounds")
    op.drop_table("season_rounds")
    # The running deploy still reads `season_rounds`; C2 drops the view
    op.execute(ROUNDS_VIEW)

    # A round taken with its season takes its ties and their series with it
    add_round_id("matches", ondelete="CASCADE")
    op.execute(
        "UPDATE matches SET round_id = (SELECT r.id FROM event_round r "
        "WHERE r.season_id = matches.season_id AND r.number = matches.playday)"
    )
    add_round_id("series", ondelete="CASCADE")
    op.execute(
        "UPDATE series SET round_id = "
        "(SELECT m.round_id FROM matches m WHERE m.id = series.match_id)"
    )

    # A renamed table keeps its index names, so the index is made again
    op.drop_index(
        op.f("ix_user_season_availability_season_id"),
        table_name="user_season_availability",
    )
    op.rename_table("user_season_availability", "round_availability")
    op.create_index(
        op.f("ix_round_availability_season_id"), "round_availability", ["season_id"]
    )
    # An answer is about one round and goes with it, so a round count can fall
    add_round_id("round_availability", ondelete="CASCADE")
    op.execute(
        "UPDATE round_availability SET round_id = (SELECT r.id FROM event_round r "
        "WHERE r.season_id = round_availability.season_id "
        "AND r.number = round_availability.playday)"
    )
    op.execute(AVAILABILITY_VIEW)

    koth_rounds()
    # B1 added the column; the table it names exists only now. A KOTH night
    # outlives its round, so the key clears the column instead of cascading.
    with op.batch_alter_table("koth_events") as batch:
        batch.create_foreign_key(
            op.f("fk_koth_events_round_id_event_round"),
            "event_round",
            ["round_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(op.f("ix_koth_events_round_id"), "koth_events", ["round_id"])


def downgrade() -> None:
    op.execute("DROP VIEW user_season_availability")
    op.execute("DROP VIEW season_rounds")

    op.drop_index(op.f("ix_koth_events_round_id"), table_name="koth_events")
    with op.batch_alter_table("koth_events") as batch:
        batch.drop_constraint(
            op.f("fk_koth_events_round_id_event_round"), type_="foreignkey"
        )

    # Only the event the nights point at, so an event an admin made stays
    bind = op.get_bind()
    event_id = bind.scalar(
        sa.text(
            "SELECT r.season_id FROM event_round r "
            "JOIN koth_events k ON k.round_id = r.id LIMIT 1"
        )
    )
    op.execute("UPDATE koth_events SET round_id = NULL")
    if event_id is not None:
        for statement in (
            "DELETE FROM event_round WHERE season_id = :event_id",
            "DELETE FROM event_stage WHERE event_id = :event_id",
            "DELETE FROM event WHERE id = :event_id",
        ):
            bind.execute(sa.text(statement), {"event_id": event_id})
        bind.execute(
            sa.text(
                "DELETE FROM league WHERE name = :name AND NOT EXISTS "
                "(SELECT 1 FROM event WHERE event.league_id = league.id)"
            ),
            {"name": KOTH_LEAGUE},
        )

    drop_round_id("round_availability", rebuild=True)
    op.drop_index(
        op.f("ix_round_availability_season_id"), table_name="round_availability"
    )
    op.rename_table("round_availability", "user_season_availability")
    op.create_index(
        op.f("ix_user_season_availability_season_id"),
        "user_season_availability",
        ["season_id"],
    )
    drop_round_id("series", rebuild=True)
    drop_round_id("matches", rebuild=True)

    op.create_table(
        "season_rounds",
        sa.Column("season_id", sa.Integer(), nullable=False),
        sa.Column("playday", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("map_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["map_id"], ["maps.id"], name=op.f("fk_season_rounds_map_id_maps")
        ),
        sa.ForeignKeyConstraint(
            ["season_id"], ["event.id"], name=op.f("fk_season_rounds_season_id_event")
        ),
        sa.PrimaryKeyConstraint("season_id", "playday", name=op.f("pk_season_rounds")),
    )
    op.create_index(op.f("ix_season_rounds_map_id"), "season_rounds", ["map_id"])
    op.execute(
        "INSERT INTO season_rounds (season_id, playday, start_date, end_date, map_id) "
        "SELECT season_id, number, start_date, end_date, map_id FROM event_round"
    )
    op.drop_index(op.f("ix_event_round_map_id"), table_name="event_round")
    op.drop_index(op.f("ix_event_round_stage_id"), table_name="event_round")
    op.drop_table("event_round")
