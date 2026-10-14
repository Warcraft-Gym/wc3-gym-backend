"""Add the cup lobby map

A free for all lobby of a cup is played on one map, drawn from the cup's pool
when the lobby is drawn and changed by a runner. `cup_series.lobby_map_id`
holds it; a two-sided series names its maps per game and leaves it null. No
existing lobby has a map, so nothing is filled.

Revision ID: f2a6c3d8b417
Revises: e5c1a9d7b246
Create Date: 2026-10-14 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2a6c3d8b417"
down_revision: str | Sequence[str] | None = "e5c1a9d7b246"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("cup_series") as batch:
        batch.add_column(sa.Column("lobby_map_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            op.f("fk_cup_series_lobby_map_id_maps"),
            "maps",
            ["lobby_map_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("cup_series") as batch:
        batch.drop_constraint(
            op.f("fk_cup_series_lobby_map_id_maps"), type_="foreignkey"
        )
        batch.drop_column("lobby_map_id")
