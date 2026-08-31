"""Add the season map settings

The map pool of a season becomes ordered, so map_season carries a position.
Existing pools are numbered by map id. seasons.map_rules names the rule of
every game of a series, comma separated: veto, loser, host or week. A week
rule reads its map from season_week_map, one row per season and playday. A
map also carries an uploaded image, the way a team carries its icon.

Revision ID: b8d3f6a20c71
Revises: d8c1f4a70b39
Create Date: 2026-08-31 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8d3f6a20c71"
down_revision: str | Sequence[str] | None = "d8c1f4a70b39"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WEEK_MAP = "season_week_map"
WEEK_MAP_INDEX = "ix_season_week_map_map_id"

# The position of a pool row is how many rows of its season sort before it
BACKFILL = """
UPDATE map_season SET position = (
    SELECT count(*) FROM map_season AS earlier
    WHERE earlier.season_id = map_season.season_id
      AND earlier.map_id < map_season.map_id
)
"""


def upgrade() -> None:
    op.add_column(
        "map_season",
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute(BACKFILL)
    op.add_column(
        "seasons", sa.Column("map_rules", sa.String(length=100), nullable=True)
    )
    op.add_column("maps", sa.Column("icon", sa.LargeBinary(), nullable=True))
    op.create_table(
        WEEK_MAP,
        sa.Column("season_id", sa.Integer(), nullable=False),
        sa.Column("playday", sa.Integer(), nullable=False),
        sa.Column("map_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["map_id"], ["maps.id"], name=op.f("fk_season_week_map_map_id_maps")
        ),
        sa.ForeignKeyConstraint(
            ["season_id"],
            ["seasons.id"],
            name=op.f("fk_season_week_map_season_id_seasons"),
        ),
        sa.PrimaryKeyConstraint(
            "season_id", "playday", name=op.f("pk_season_week_map")
        ),
    )
    op.create_index(op.f(WEEK_MAP_INDEX), WEEK_MAP, ["map_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f(WEEK_MAP_INDEX), table_name=WEEK_MAP)
    op.drop_table(WEEK_MAP)
    op.drop_column("maps", "icon")
    op.drop_column("seasons", "map_rules")
    op.drop_column("map_season", "position")
