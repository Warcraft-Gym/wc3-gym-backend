"""Add the cup rounds

A cup can be played over several rounds, each a competition of its own on its
own date. `cup_leg` holds the rounds, `cup_leg_stage` names the round each of
the cup's stages is played in, and `cup_leg_checkin` the players who play a
round. The points each place of a round pays go in
`cup_settings.points_by_place`. No existing cup plays rounds, so nothing is
filled.

Revision ID: d3b8f1a6c925
Revises: c7d2e9a4f183
Create Date: 2026-10-13 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d3b8f1a6c925"
down_revision: str | Sequence[str] | None = "c7d2e9a4f183"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cup_leg",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["event.id"],
            name=op.f("fk_cup_leg_event_id_event"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cup_leg")),
    )
    op.create_index(op.f("ix_cup_leg_event_id"), "cup_leg", ["event_id"], unique=False)
    op.create_table(
        "cup_leg_stage",
        sa.Column("stage_id", sa.Integer(), nullable=False),
        sa.Column("leg_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["stage_id"],
            ["event_stage.id"],
            name=op.f("fk_cup_leg_stage_stage_id_event_stage"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["leg_id"],
            ["cup_leg.id"],
            name=op.f("fk_cup_leg_stage_leg_id_cup_leg"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("stage_id", name=op.f("pk_cup_leg_stage")),
    )
    op.create_index(
        op.f("ix_cup_leg_stage_leg_id"), "cup_leg_stage", ["leg_id"], unique=False
    )
    op.create_table(
        "cup_leg_checkin",
        sa.Column("leg_id", sa.Integer(), nullable=False),
        sa.Column("entrant_id", sa.Integer(), nullable=False),
        sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["leg_id"],
            ["cup_leg.id"],
            name=op.f("fk_cup_leg_checkin_leg_id_cup_leg"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["entrant_id"],
            ["event_entrant.id"],
            name=op.f("fk_cup_leg_checkin_entrant_id_event_entrant"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "leg_id", "entrant_id", name=op.f("pk_cup_leg_checkin")
        ),
    )
    with op.batch_alter_table("cup_settings") as batch:
        batch.add_column(
            sa.Column("points_by_place", sa.String(length=200), nullable=True)
        )


def downgrade() -> None:
    # A cup played over rounds reads, on the older schema, as one cup holding
    # every round's stages in a row
    with op.batch_alter_table("cup_settings") as batch:
        batch.drop_column("points_by_place")
    op.drop_table("cup_leg_checkin")
    op.drop_index(op.f("ix_cup_leg_stage_leg_id"), table_name="cup_leg_stage")
    op.drop_table("cup_leg_stage")
    op.drop_index(op.f("ix_cup_leg_event_id"), table_name="cup_leg")
    op.drop_table("cup_leg")
