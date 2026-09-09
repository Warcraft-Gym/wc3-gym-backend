"""Keep the off race of a series side

A player may play one series on another race. The two columns hold that race
and read null when he played the race he signed the season up on, so every
answer resolves a side's race as the off race over the signup race.

Revision ID: d4b6e2f1c907
Revises: d7e3a9c1f5b2
Create Date: 2026-09-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d4b6e2f1c907"
down_revision: str | Sequence[str] | None = "a4c1e08b6d27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RACES = ("RANDOM", "HU", "OC", "NE", "UD")


def race_type() -> sa.Enum:
    """The race enum. Postgres already holds the type, so it is not created again."""
    if op.get_bind().dialect.name == "postgresql":
        return postgresql.ENUM(*RACES, name="race", create_type=False)
    return sa.Enum(*RACES, name="race")


def upgrade() -> None:
    op.add_column("series", sa.Column("player1_off_race", race_type(), nullable=True))
    op.add_column("series", sa.Column("player2_off_race", race_type(), nullable=True))


def downgrade() -> None:
    op.drop_column("series", "player2_off_race")
    op.drop_column("series", "player1_off_race")
