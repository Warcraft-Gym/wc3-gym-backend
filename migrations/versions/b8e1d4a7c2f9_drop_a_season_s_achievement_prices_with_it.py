"""Drop a season's achievement prices with it

A season is created with a price row per rule, and those rows pointed at
the season with no cascade, so deleting any real season failed on the
foreign key. The rows now go with the season.

Revision ID: b8e1d4a7c2f9
Revises: a3f7c2d9e5b1
Create Date: 2026-09-05 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8e1d4a7c2f9"
down_revision: str | Sequence[str] | None = "a3f7c2d9e5b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "ladder_achievements"
FK = "fk_ladder_achievements_season_id_seasons"
# the constraint was created without a name; SQLite reflects none, so the convention names it
CONVENTION = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}


def _current_name() -> str:
    for fk in sa.inspect(op.get_bind()).get_foreign_keys(TABLE):
        if fk["constrained_columns"] == ["season_id"]:
            return fk["name"] or FK
    raise RuntimeError(f"{TABLE}.season_id has no foreign key")


def _repoint(ondelete: str | None) -> None:
    name = _current_name()
    with op.batch_alter_table(TABLE, naming_convention=CONVENTION) as batch:
        batch.drop_constraint(name, type_="foreignkey")
        batch.create_foreign_key(
            op.f(FK), "seasons", ["season_id"], ["id"], ondelete=ondelete
        )


def upgrade() -> None:
    _repoint("CASCADE")


def downgrade() -> None:
    _repoint(None)
