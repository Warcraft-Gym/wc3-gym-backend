"""Drop the dead team season map counts

No service writes team_season.maps_won or team_season.maps_lost, and no API
response carries them. The downgrade recreates them empty.

Revision ID: b7e2d4a91c05
Revises: 9f4b7c1d2ae5
Create Date: 2026-08-20 10:12:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7e2d4a91c05"
down_revision: str | Sequence[str] | None = "9f4b7c1d2ae5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MAP_COUNTS = ("maps_won", "maps_lost")


def upgrade() -> None:
    for column in MAP_COUNTS:
        op.drop_column("team_season", column)


def downgrade() -> None:
    for column in MAP_COUNTS:
        op.add_column("team_season", sa.Column(column, sa.Integer(), nullable=True))
