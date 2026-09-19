"""Add the event and stage draft settings

Four settings: early check-in and the round end zone on the event, the W3C
season window the min-games warning counts over, and the largest MMR
difference a captain draft pairs inside on the stage.

Revision ID: a2f4c8d1b607
Revises: 70274e9b1dbb
Create Date: 2026-09-19 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a2f4c8d1b607"
down_revision: str | Sequence[str] | None = "70274e9b1dbb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# A batch rebuild of `event` loses its self-referencing key on SQLite, so these
# columns are added and dropped in place.
def upgrade() -> None:
    op.add_column(
        "event",
        sa.Column(
            "early_checkin", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "event", sa.Column("round_end_zone", sa.String(length=64), nullable=True)
    )
    op.add_column("event", sa.Column("min_games_seasons", sa.Integer(), nullable=True))
    op.add_column(
        "event_stage", sa.Column("max_mmr_difference", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("event_stage", "max_mmr_difference")
    op.drop_column("event", "min_games_seasons")
    op.drop_column("event", "round_end_zone")
    op.drop_column("event", "early_checkin")
