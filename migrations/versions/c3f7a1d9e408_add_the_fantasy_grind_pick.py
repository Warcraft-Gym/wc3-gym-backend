"""Add the fantasy grind pick

A season may offer the pick, and a fantasy team names the team it picked. Both
columns open empty: no season offers the pick and no fantasy team holds one.

Revision ID: c3f7a1d9e408
Revises: f2b7c4d9e1a3
Create Date: 2026-09-07 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3f7a1d9e408"
down_revision: str | Sequence[str] | None = "f2b7c4d9e1a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FANTASY_TEAMS = "fantasy_teams"
FK = "fk_fantasy_teams_grind_team_id_teams"
IX = "ix_fantasy_teams_grind_team_id"
# The key that names a fantasy team once per season, as f7a2c95e3b18 built it
KEY = "uq_fantasy_teams_season_id_name"
KEY_SQL = f"CREATE UNIQUE INDEX {KEY} ON {FANTASY_TEAMS} (season_id, lower(trim(name)))"


def _keep_the_name_key() -> None:
    """SQLite runs the batch as a table copy and reads no expression index, so
    the name key is dropped with the old table and built again here."""
    if op.get_bind().dialect.name == "sqlite":
        op.execute(KEY_SQL)


def upgrade() -> None:
    op.add_column(
        "seasons",
        sa.Column(
            "fantasy_grind", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    with op.batch_alter_table(FANTASY_TEAMS) as batch:
        batch.add_column(sa.Column("grind_team_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            op.f(FK), "teams", ["grind_team_id"], ["id"], ondelete="SET NULL"
        )
    _keep_the_name_key()
    op.create_index(op.f(IX), FANTASY_TEAMS, ["grind_team_id"])


def downgrade() -> None:
    op.drop_index(op.f(IX), table_name=FANTASY_TEAMS)
    with op.batch_alter_table(FANTASY_TEAMS) as batch:
        batch.drop_constraint(op.f(FK), type_="foreignkey")
        batch.drop_column("grind_team_id")
    _keep_the_name_key()
    op.drop_column("seasons", "fantasy_grind")
