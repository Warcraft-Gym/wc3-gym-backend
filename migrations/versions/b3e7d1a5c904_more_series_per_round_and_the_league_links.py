"""More series per round, and the league links

Two additive changes. A round robin stage says how many series each entrant
plays per round, so a division of eight covers its seven opponents in four
rounds. A league carries the rules page and the stream the events of the
league run on.

Revision ID: b3e7d1a5c904
Revises: a7c4f19d0b58
Create Date: 2026-09-13 23:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3e7d1a5c904"
down_revision: str | Sequence[str] | None = "a7c4f19d0b58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEAGUE_LINKS = ("rules_url", "stream_url")


def upgrade() -> None:
    op.add_column(
        "event_stage",
        sa.Column(
            "series_per_entrant_per_round",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    for name in LEAGUE_LINKS:
        op.add_column("league", sa.Column(name, sa.String(length=500), nullable=True))


def downgrade() -> None:
    for name in LEAGUE_LINKS:
        op.drop_column("league", name)
    op.drop_column("event_stage", "series_per_entrant_per_round")
