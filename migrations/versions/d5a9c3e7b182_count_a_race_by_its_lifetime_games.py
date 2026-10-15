"""Count a race by its lifetime games, and keep how far a player's history goes

An event names the lifetime games a race needs before its rating counts, so a
rating from a handful of games on another race never stands for the player;
the cups take 20. A player's stats of past W3C seasons are kept once read, and
the stamp says the newest season they cover.

Revision ID: d5a9c3e7b182
Revises: c7e2b9d4a613
Create Date: 2026-10-08 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5a9c3e7b182"
down_revision: str | Sequence[str] | None = "c7e2b9d4a613"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("event", sa.Column("race_games_min", sa.Integer(), nullable=True))
    # the cups rate a player on the races they have really played
    op.execute("UPDATE event SET race_games_min = 20 WHERE kind = 'cup'")
    op.add_column(
        "users", sa.Column("w3c_history_through", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("users", "w3c_history_through")
    op.drop_column("event", "race_games_min")
