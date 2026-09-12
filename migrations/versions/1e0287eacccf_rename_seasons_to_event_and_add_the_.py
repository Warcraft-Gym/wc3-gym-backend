"""Rename seasons to event and add the league tables

Every series will hang off a round of a stage of an event, and a GNL season
is one event of the GNL league. This is the first of the four deploys: the
table is renamed with its ids kept, an updatable `seasons` view stands in
for it while the running deploy still reads that name, and the league,
stage, division and entrant tables arrive empty beside it.

The data the rename needs: one "GNL" league that every existing event joins,
and one round-robin stage per event carrying the event's map rules, so the
GNL rounds have a stage to hang off in C1.

Revision ID: 1e0287eacccf
Revises: 75b9f3b280c2
Create Date: 2026-09-12 02:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "1e0287eacccf"
down_revision: str | Sequence[str] | None = "75b9f3b280c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENUM_VALUES = {
    "entrantkind": ("solo", "drafted_teams"),
    "eventkind": ("gnl", "cup", "koth", "signup"),
    "stageformat": (
        "round_robin",
        "single_elimination",
        "double_elimination",
        "swiss",
        "koth",
        "ffa",
    ),
    "schedulingmode": ("assigned", "agreed", "immediate"),
    "signupchannel": ("web", "bot", "twitch"),
    # Already in the database; this migration only refers to it
    "race": ("RANDOM", "HU", "OC", "NE", "UD"),
}
NEW_TYPES = [name for name in ENUM_VALUES if name != "race"]


def enum_type(name: str) -> sa.Enum:
    """A reference to an enum type. On Postgres the type is created once, up
    front, so no table that uses it creates it again."""
    values = ENUM_VALUES[name]
    if op.get_bind().dialect.name == "postgresql":
        return postgresql.ENUM(*values, name=name, create_type=False)
    return sa.Enum(*values, name=name)


def event_columns() -> list[sa.Column]:
    """The event columns, all nullable or defaulted, so the seasons view stays
    writable while the running deploy still inserts through it."""
    return [
        sa.Column("kind", enum_type("eventkind"), nullable=False, server_default="gnl"),
        sa.Column("published", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("checkin_opens_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checkin_closes_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("page_url", sa.String(length=500), nullable=True),
        sa.Column("stream_url", sa.String(length=500), nullable=True),
        sa.Column("discord_event_id", sa.String(length=50), nullable=True),
        sa.Column("description", sa.String(length=2000), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("min_games", sa.Integer(), nullable=True),
        sa.Column("mmr_max", sa.Integer(), nullable=True),
        sa.Column("entrant_cap", sa.Integer(), nullable=True),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    # Postgres needs the types before the columns; SQLite has nothing to create
    for name in NEW_TYPES:
        sa.Enum(*ENUM_VALUES[name], name=name).create(bind, checkfirst=True)

    op.create_table(
        "league",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("short_name", sa.String(length=20), nullable=True),
        sa.Column("page_url", sa.String(length=500), nullable=True),
        sa.Column(
            "entrant_kind",
            enum_type("entrantkind"),
            nullable=False,
            server_default="solo",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_league")),
        sa.UniqueConstraint("name", name=op.f("uq_league_name")),
    )

    op.rename_table("seasons", "event")
    # No batch_alter_table: recreating the table on SQLite would drop the
    # expression index behind the season name key.
    for column in event_columns():
        op.add_column("event", column)
    if bind.dialect.name == "sqlite":
        # SQLite alters no constraint, but it takes REFERENCES on a column it adds
        op.execute(
            "ALTER TABLE event ADD COLUMN league_id INTEGER REFERENCES league (id)"
        )
    else:
        op.add_column("event", sa.Column("league_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            op.f("fk_event_league_id_league"), "event", "league", ["league_id"], ["id"]
        )
    op.create_index(op.f("ix_event_league_id"), "event", ["league_id"])

    # Every season that exists today is a GNL season
    op.execute(
        "INSERT INTO league (name, short_name, entrant_kind) "
        "VALUES ('GNL', 'GNL', 'drafted_teams')"
    )
    op.execute(
        "UPDATE event SET league_id = (SELECT id FROM league WHERE name = 'GNL')"
    )

    op.create_table(
        "event_stage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=True),
        sa.Column(
            "format",
            enum_type("stageformat"),
            nullable=False,
            server_default="round_robin",
        ),
        sa.Column("best_of", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("map_rules", sa.String(length=100), nullable=True),
        sa.Column(
            "scheduling_mode",
            enum_type("schedulingmode"),
            nullable=False,
            server_default="agreed",
        ),
        sa.Column(
            "ranking_rule",
            sa.String(length=100),
            nullable=False,
            server_default="points,game_diff,head_to_head",
        ),
        sa.Column(
            "points_series_won", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column(
            "points_series_drawn", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("points_game_won", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("advance_count", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["event.id"],
            name=op.f("fk_event_stage_event_id_event"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event_stage")),
        sa.UniqueConstraint(
            "event_id", "position", name=op.f("uq_event_stage_event_id")
        ),
    )
    op.create_index(op.f("ix_event_stage_event_id"), "event_stage", ["event_id"])

    op.create_table(
        "event_division",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=True),
        sa.Column("lower_bound", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["event.id"],
            name=op.f("fk_event_division_event_id_event"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event_division")),
        sa.UniqueConstraint(
            "event_id", "position", name=op.f("uq_event_division_event_id")
        ),
    )
    op.create_index(op.f("ix_event_division_event_id"), "event_division", ["event_id"])

    op.create_table(
        "event_entrant",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("race", enum_type("race"), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("division_id", sa.Integer(), nullable=True),
        sa.Column(
            "channel", enum_type("signupchannel"), nullable=False, server_default="web"
        ),
        sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["event.id"],
            name=op.f("fk_event_entrant_event_id_event"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_event_entrant_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["division_id"],
            ["event_division.id"],
            name=op.f("fk_event_entrant_division_id_event_division"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event_entrant")),
        sa.UniqueConstraint(
            "event_id", "user_id", name=op.f("uq_event_entrant_event_id")
        ),
    )
    op.create_index(op.f("ix_event_entrant_event_id"), "event_entrant", ["event_id"])
    op.create_index(op.f("ix_event_entrant_user_id"), "event_entrant", ["user_id"])

    # One round-robin stage per season, carrying the season's map rules, so the
    # GNL rounds have a stage to hang off in C1
    op.execute(
        "INSERT INTO event_stage (event_id, position, format, best_of, map_rules, "
        "scheduling_mode, ranking_rule, points_series_won, points_series_drawn, "
        "points_game_won) SELECT id, 1, 'round_robin', 3, map_rules, 'agreed', "
        "'points,game_diff,head_to_head', 1, 0, 0 FROM event"
    )

    # C1 dates one round per KOTH night and fills this in
    op.add_column("koth_events", sa.Column("round_id", sa.Integer(), nullable=True))

    # The running deploy still reads `seasons`. Auto-updatable on Postgres,
    # read-only on SQLite, which nothing writes through. Dropped in B2.
    op.execute("CREATE VIEW seasons AS SELECT * FROM event")


def downgrade() -> None:
    op.execute("DROP VIEW seasons")
    op.drop_column("koth_events", "round_id")
    op.drop_table("event_entrant")
    op.drop_table("event_division")
    op.drop_table("event_stage")
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint(
            op.f("fk_event_league_id_league"), "event", type_="foreignkey"
        )
    op.drop_index(op.f("ix_event_league_id"), table_name="event")
    op.drop_column("event", "league_id")
    for column in reversed(event_columns()):
        op.drop_column("event", column.name)
    op.rename_table("event", "seasons")
    op.drop_table("league")
    for name in NEW_TYPES:
        sa.Enum(*ENUM_VALUES[name], name=name).drop(op.get_bind(), checkfirst=True)
