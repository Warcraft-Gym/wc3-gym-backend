"""The Swiss, FFA and award rows

The one expand migration of the sixth events deploy, and every change is
additive. A stage says how many rounds a Swiss draws, how many players an FFA
lobby seats and what each place of that lobby pays. An entrant carries the
group a group stage puts him in.

`series_side` holds one row per side of a series that is not a plain 1v1: an
FFA seat, or one player of a team side. Its key is the series, the side and
the player, and a key column takes no null, so `user_id` is 0 where the row
names no player yet and carries no foreign key of its own.

`event_award` is what an event hands out when it closes, one row per place,
so a trophy read lists a cup win beside a season championship.

Revision ID: c9f2b6a41d38
Revises: b4e1c9a7d206
Create Date: 2026-09-14 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9f2b6a41d38"
down_revision: str | Sequence[str] | None = "b4e1c9a7d206"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SIDE = "series_side"
AWARD = "event_award"
# The stage columns the Swiss and the FFA formats read, all nullable
STAGE_COLUMNS = (
    ("swiss_rounds", sa.Integer()),
    ("points_by_place", sa.String(length=50)),
    ("lobby_size", sa.Integer()),
)


def upgrade() -> None:
    for name, kind in STAGE_COLUMNS:
        op.add_column("event_stage", sa.Column(name, kind, nullable=True))
    op.add_column("event_entrant", sa.Column("group_no", sa.Integer(), nullable=True))

    op.create_table(
        SIDE,
        sa.Column("series_id", sa.Integer(), nullable=False),
        sa.Column("side_no", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("entrant_id", sa.Integer(), nullable=True),
        sa.Column("place", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["series_id"],
            ["series.id"],
            name=op.f("fk_series_side_series_id_series"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["entrant_id"],
            ["event_entrant.id"],
            name=op.f("fk_series_side_entrant_id_event_entrant"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint(
            "series_id", "side_no", "user_id", name=op.f("pk_series_side")
        ),
    )
    op.create_index(op.f("ix_series_side_user_id"), SIDE, ["user_id"])

    op.create_table(
        AWARD,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("entrant_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("team_id", sa.Integer(), nullable=True),
        sa.Column("place", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=50), nullable=False),
        sa.Column("awarded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["event.id"],
            name=op.f("fk_event_award_event_id_event"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["entrant_id"],
            ["event_entrant.id"],
            name=op.f("fk_event_award_entrant_id_event_entrant"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_event_award_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
            name=op.f("fk_event_award_team_id_teams"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event_award")),
    )
    op.create_index(op.f("ix_event_award_event_id"), AWARD, ["event_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_event_award_event_id"), table_name=AWARD)
    op.drop_table(AWARD)
    op.drop_index(op.f("ix_series_side_user_id"), table_name=SIDE)
    op.drop_table(SIDE)
    op.drop_column("event_entrant", "group_no")
    for name, _ in STAGE_COLUMNS:
        op.drop_column("event_stage", name)
