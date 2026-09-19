"""Add the round draft state

Who wrote and who changed a drafted pairing, the published series a pairing
replaces, the Ready and seen marks of each team, and the working largest MMR
difference of a fixture.

Revision ID: c6d2f1a83b95
Revises: a2f4c8d1b607
Create Date: 2026-09-19 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c6d2f1a83b95"
down_revision: str | Sequence[str] | None = "a2f4c8d1b607"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KEYS = (
    ("created_by_user_id", "users", "SET NULL"),
    ("updated_by_user_id", "users", "SET NULL"),
    ("replaces_series_id", "series", "CASCADE"),
)


def upgrade() -> None:
    # SQLite takes a foreign key only while the table is rebuilt
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("draft_series") as batch:
            batch.add_column(
                sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True)
            )
            for column, table, rule in KEYS:
                batch.add_column(sa.Column(column, sa.Integer(), nullable=True))
                batch.create_foreign_key(
                    op.f(f"fk_draft_series_{column}_{table}"),
                    table,
                    [column],
                    ["id"],
                    ondelete=rule,
                )
    else:
        op.add_column(
            "draft_series",
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )
        for column, table, rule in KEYS:
            op.add_column(
                "draft_series", sa.Column(column, sa.Integer(), nullable=True)
            )
            op.create_foreign_key(
                op.f(f"fk_draft_series_{column}_{table}"),
                "draft_series",
                table,
                [column],
                ["id"],
                ondelete=rule,
            )
    op.create_index(
        op.f("ix_draft_series_replaces_series_id"),
        "draft_series",
        ["replaces_series_id"],
    )

    op.create_table(
        "match_draft_mark",
        sa.Column("match_id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("ready_by_user_id", sa.Integer(), nullable=True),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["match_id"],
            ["matches.id"],
            name=op.f("fk_match_draft_mark_match_id_matches"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ready_by_user_id"],
            ["users.id"],
            name=op.f("fk_match_draft_mark_ready_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
            name=op.f("fk_match_draft_mark_team_id_teams"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "match_id", "team_id", name=op.f("pk_match_draft_mark")
        ),
    )
    op.create_table(
        "match_draft_state",
        sa.Column("match_id", sa.Integer(), nullable=False),
        sa.Column("max_mmr_difference", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["match_id"],
            ["matches.id"],
            name=op.f("fk_match_draft_state_match_id_matches"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("match_id", name=op.f("pk_match_draft_state")),
    )


def downgrade() -> None:
    op.drop_table("match_draft_state")
    op.drop_table("match_draft_mark")
    op.drop_index(op.f("ix_draft_series_replaces_series_id"), table_name="draft_series")
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("draft_series") as batch:
            for column, table, _ in KEYS:
                batch.drop_constraint(
                    op.f(f"fk_draft_series_{column}_{table}"), type_="foreignkey"
                )
                batch.drop_column(column)
            batch.drop_column("updated_at")
    else:
        for column, table, _ in KEYS:
            op.drop_constraint(
                op.f(f"fk_draft_series_{column}_{table}"),
                "draft_series",
                type_="foreignkey",
            )
            op.drop_column("draft_series", column)
        op.drop_column("draft_series", "updated_at")
