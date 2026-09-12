"""Series need a round

The last of the four deploys of the events model. The `season_rounds` and
`user_season_availability` views go, and the round every row was given in C1
becomes a requirement: a match, a series and an availability answer each name
one.

A series may now sit outside a team tie, so `match_id` takes a null. The pair
(match_id, round_id) is a foreign key into `matches (id, round_id)`, so a
series inside a tie is always played in the tie's round, and a series without
a tie meets a pair of players once per round.

Revision ID: 1aa65a77d894
Revises: 96c0d36de81c
Create Date: 2026-09-12 08:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1aa65a77d894"
down_revision: str | Sequence[str] | None = "96c0d36de81c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROUNDS_VIEW = (
    "CREATE VIEW season_rounds AS SELECT season_id, number AS playday, "
    "start_date, end_date, map_id FROM event_round"
)
AVAILABILITY_VIEW = (
    "CREATE VIEW user_season_availability AS SELECT user_id, season_id, playday, "
    "available, set_by_user_id FROM round_availability"
)
COMPOSITE_FK = op.f("fk_series_match_id_round_id_matches")
PAIR_PER_ROUND = op.f("uq_series_round_id_player1_id_player2_id")
MATCH_ROUND = op.f("uq_matches_id_round_id")
AVAILABILITY_COLUMNS = "user_id, season_id, playday, round_id, available, set_by_user_id"


def rebuild_availability(key: list[str], round_nullable: bool) -> None:
    """Write round_availability again under `key`, carrying every row over.

    SQLite alters no primary key in place, and on Postgres the one this table
    holds is still named after user_season_availability, so both dialects take
    the copy.
    """
    op.create_table(
        "round_availability_new",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("season_id", sa.Integer(), nullable=False),
        sa.Column("playday", sa.Integer(), nullable=False),
        sa.Column("round_id", sa.Integer(), nullable=round_nullable),
        sa.Column("available", sa.Boolean(), nullable=False),
        sa.Column("set_by_user_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_round_availability_user_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["season_id"],
            ["event.id"],
            name=op.f("fk_round_availability_season_id_event"),
        ),
        sa.ForeignKeyConstraint(
            ["set_by_user_id"],
            ["users.id"],
            name=op.f("fk_round_availability_set_by_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["round_id"],
            ["event_round.id"],
            name=op.f("fk_round_availability_round_id_event_round"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(*key, name=op.f("pk_round_availability")),
    )
    op.execute(
        f"INSERT INTO round_availability_new ({AVAILABILITY_COLUMNS}) "
        f"SELECT {AVAILABILITY_COLUMNS} FROM round_availability"
    )
    for index in ("ix_round_availability_season_id", "ix_round_availability_round_id"):
        op.drop_index(op.f(index), table_name="round_availability")
    op.drop_table("round_availability")
    op.rename_table("round_availability_new", "round_availability")
    op.create_index(
        op.f("ix_round_availability_season_id"), "round_availability", ["season_id"]
    )
    op.create_index(
        op.f("ix_round_availability_round_id"), "round_availability", ["round_id"]
    )


def upgrade() -> None:
    op.execute("DROP VIEW user_season_availability")
    op.execute("DROP VIEW season_rounds")

    # An answer about a round no season ever held; the dashboard asks about none
    op.execute("DELETE FROM round_availability WHERE round_id IS NULL")

    with op.batch_alter_table("matches") as batch:
        batch.alter_column("round_id", existing_type=sa.Integer(), nullable=False)
    # The parent key the series pair points at
    op.create_index(MATCH_ROUND, "matches", ["id", "round_id"], unique=True)

    with op.batch_alter_table("series") as batch:
        batch.alter_column("round_id", existing_type=sa.Integer(), nullable=False)
        # A series outside a team tie names no match
        batch.alter_column("match_id", existing_type=sa.Integer(), nullable=True)
        batch.create_foreign_key(
            COMPOSITE_FK,
            "matches",
            ["match_id", "round_id"],
            ["id", "round_id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        )
    # Two players meet once in a round when no tie groups them
    op.create_index(
        PAIR_PER_ROUND,
        "series",
        ["round_id", "player1_id", "player2_id"],
        unique=True,
        postgresql_where=sa.text("match_id IS NULL"),
        sqlite_where=sa.text("match_id IS NULL"),
    )

    rebuild_availability(["user_id", "round_id"], round_nullable=False)


def downgrade() -> None:
    rebuild_availability(["user_id", "season_id", "playday"], round_nullable=True)

    op.drop_index(PAIR_PER_ROUND, table_name="series")
    # The older shape holds no series outside a team tie
    op.execute("DELETE FROM series WHERE match_id IS NULL")
    with op.batch_alter_table("series") as batch:
        batch.drop_constraint(COMPOSITE_FK, type_="foreignkey")
        batch.alter_column("match_id", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("round_id", existing_type=sa.Integer(), nullable=True)

    op.drop_index(MATCH_ROUND, table_name="matches")
    with op.batch_alter_table("matches") as batch:
        batch.alter_column("round_id", existing_type=sa.Integer(), nullable=True)

    op.execute(ROUNDS_VIEW)
    op.execute(AVAILABILITY_VIEW)
