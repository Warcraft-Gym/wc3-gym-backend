"""Preserve archival event participants results and videos

Revision ID: 14261ed1246f
Revises: e4b8c2f6a913
Create Date: 2026-09-26 11:17:17.904594

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "14261ed1246f"
down_revision: str | Sequence[str] | None = "e4b8c2f6a913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "event_video",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column(
            "provider", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False
        ),
        sa.Column(
            "video_key", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False
        ),
        sa.Column("url", sqlmodel.sql.sqltypes.AutoString(length=500), nullable=False),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
        sa.Column("kind", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["event.id"],
            name=op.f("fk_event_video_event_id_event"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event_video")),
        sa.UniqueConstraint(
            "event_id", "provider", "video_key", name=op.f("uq_event_video_event_id")
        ),
    )
    op.create_index(
        op.f("ix_event_video_event_id"), "event_video", ["event_id"], unique=False
    )
    op.create_table(
        "historical_participant",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column(
            "source_key", sqlmodel.sql.sqltypes.AutoString(length=200), nullable=False
        ),
        sa.Column(
            "source_name", sqlmodel.sql.sqltypes.AutoString(length=200), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["event.id"],
            name=op.f("fk_historical_participant_event_id_event"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_historical_participant")),
        sa.UniqueConstraint(
            "event_id", "source_key", name=op.f("uq_historical_participant_event_id")
        ),
    )
    op.create_index(
        op.f("ix_historical_participant_event_id"),
        "historical_participant",
        ["event_id"],
        unique=False,
    )
    op.create_table(
        "koth_history_event",
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column(
            "source_key", sqlmodel.sql.sqltypes.AutoString(length=200), nullable=False
        ),
        sa.Column(
            "source_url", sqlmodel.sql.sqltypes.AutoString(length=500), nullable=False
        ),
        sa.Column(
            "source_digest", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False
        ),
        sa.Column(
            "date_label", sqlmodel.sql.sqltypes.AutoString(length=200), nullable=False
        ),
        sa.Column("source_record", sa.JSON(), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["event.id"],
            name=op.f("fk_koth_history_event_event_id_event"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_koth_history_event")),
        sa.UniqueConstraint(
            "source_key", name=op.f("uq_koth_history_event_source_key")
        ),
    )
    op.create_table(
        "koth_history_series",
        sa.Column("series_id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column(
            "source_key", sqlmodel.sql.sqltypes.AutoString(length=200), nullable=False
        ),
        sa.Column("source_record", sa.JSON(), nullable=False),
        sa.Column("inferred_winner", sa.Integer(), nullable=True),
        sa.Column(
            "review_note", sqlmodel.sql.sqltypes.AutoString(length=200), nullable=True
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["event.id"],
            name=op.f("fk_koth_history_series_event_id_event"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["series_id"],
            ["series.id"],
            name=op.f("fk_koth_history_series_series_id_series"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("series_id", name=op.f("pk_koth_history_series")),
        sa.UniqueConstraint(
            "event_id", "source_key", name=op.f("uq_koth_history_series_event_id")
        ),
    )
    op.create_index(
        op.f("ix_koth_history_series_event_id"),
        "koth_history_series",
        ["event_id"],
        unique=False,
    )
    with op.batch_alter_table("event_entrant") as batch:
        batch.add_column(
            sa.Column("historical_participant_id", sa.Integer(), nullable=True)
        )
        batch.create_unique_constraint(
            "uq_event_entrant_historical_participant_id", ["historical_participant_id"]
        )
        batch.create_foreign_key(
            op.f("fk_event_entrant_historical_participant_id_historical_participant"),
            "historical_participant",
            ["historical_participant_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.drop_constraint(op.f("ck_event_entrant_one_entrant"), type_="check")
        batch.create_check_constraint(
            op.f("ck_event_entrant_one_entrant"),
            "(CASE WHEN user_id IS NULL THEN 0 ELSE 1 END + CASE WHEN team_id IS NULL THEN 0 ELSE 1 END + CASE WHEN historical_participant_id IS NULL THEN 0 ELSE 1 END) = 1",
        )
    with op.batch_alter_table("series") as batch:
        batch.add_column(
            sa.Column(
                "result_unavailable",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            )
        )
        batch.create_check_constraint(
            op.f("ck_series_unknown_result_scores"),
            "NOT result_unavailable OR (player1_score IS NULL AND player2_score IS NULL)",
        )
    with op.batch_alter_table("series_game") as batch:
        batch.alter_column("winner_side", existing_type=sa.String(1), nullable=True)
    with op.batch_alter_table("event_award") as batch:
        batch.alter_column(
            "awarded_at", existing_type=sa.DateTime(timezone=True), nullable=True
        )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT COUNT(*) FROM historical_participant")):
        raise RuntimeError("Archive participants must be reconciled before downgrading")
    if connection.scalar(
        sa.text("SELECT COUNT(*) FROM series_game WHERE winner_side IS NULL")
    ):
        raise RuntimeError("Unknown results cannot be represented by the older schema")
    if connection.scalar(
        sa.text("SELECT COUNT(*) FROM event_award WHERE awarded_at IS NULL")
    ):
        raise RuntimeError(
            "Unknown award dates cannot be represented by the older schema"
        )
    with op.batch_alter_table("event_award") as batch:
        batch.alter_column(
            "awarded_at", existing_type=sa.DateTime(timezone=True), nullable=False
        )
    with op.batch_alter_table("series_game") as batch:
        batch.alter_column("winner_side", existing_type=sa.String(1), nullable=False)
    with op.batch_alter_table("series") as batch:
        batch.drop_constraint(op.f("ck_series_unknown_result_scores"), type_="check")
        batch.drop_column("result_unavailable")
    with op.batch_alter_table("event_entrant") as batch:
        batch.drop_constraint(
            op.f("fk_event_entrant_historical_participant_id_historical_participant"),
            type_="foreignkey",
        )
        batch.drop_constraint(
            "uq_event_entrant_historical_participant_id", type_="unique"
        )
        batch.drop_constraint(op.f("ck_event_entrant_one_entrant"), type_="check")
        batch.drop_column("historical_participant_id")
        batch.create_check_constraint(
            op.f("ck_event_entrant_one_entrant"),
            "(CASE WHEN user_id IS NULL THEN 0 ELSE 1 END + CASE WHEN team_id IS NULL THEN 0 ELSE 1 END) = 1",
        )
    for name in (
        "koth_history_series",
        "koth_history_event",
        "historical_participant",
        "event_video",
    ):
        op.drop_table(name)
