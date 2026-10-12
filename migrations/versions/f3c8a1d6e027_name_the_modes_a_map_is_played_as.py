"""Name the modes a map is played as

A map names the modes it is played as, 1v1 to 8v8 and FFA, so a cup offers the
maps of its own mode first. The maps of a GNL season's pool are 1v1 maps.

Revision ID: f3c8a1d6e027
Revises: e7b4f2a9c5d1
Create Date: 2026-10-08 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3c8a1d6e027"
down_revision: str | Sequence[str] | None = "e7b4f2a9c5d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "maps",
        sa.Column("modes", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    )
    # a GNL season plays 1v1, so every map of a GNL pool is a 1v1 map
    op.execute(
        "UPDATE maps SET modes = '1v1' WHERE id IN ("
        "SELECT map_season.map_id FROM map_season "
        "JOIN event ON event.id = map_season.season_id WHERE event.kind = 'gnl')"
    )


def downgrade() -> None:
    op.drop_column("maps", "modes")
