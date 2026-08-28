"""Keep the race a player registered on for a season

The ladder scores a player on his league race, so that race has to belong to
the season rather than to the player. Existing rows read null, which means
the race was never recorded and the ladder falls back to `users.race`.

Revision ID: c5b8e0a41d67
Revises: a3d7f0c81b62
Create Date: 2026-08-28 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c5b8e0a41d67"
down_revision: str | Sequence[str] | None = "a3d7f0c81b62"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RACES = ("RANDOM", "HU", "OC", "NE", "UD")


def race_type() -> sa.Enum:
    """The race enum. Postgres already holds the type, so it is not created again."""
    if op.get_bind().dialect.name == "postgresql":
        return postgresql.ENUM(*RACES, name="race", create_type=False)
    return sa.Enum(*RACES, name="race")


def upgrade() -> None:
    op.add_column("user_season_signup", sa.Column("race", race_type(), nullable=True))


def downgrade() -> None:
    op.drop_column("user_season_signup", "race")
