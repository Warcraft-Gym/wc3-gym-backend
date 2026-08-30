"""Rename the coach seat to captain

The seat a team names for a season is a captain, so the table, its indexes and
the Discord binding kind spell it that way.

Revision ID: e7b4d0a35c19
Revises: a1c7e04b52f9
Create Date: 2026-08-30 15:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7b4d0a35c19"
down_revision: str | Sequence[str] | None = "a1c7e04b52f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEXED = ("season_id", "user_id")
CONSTRAINTS = (
    "pk_{0}",
    "fk_{0}_season_id_seasons",
    "fk_{0}_team_id_teams",
    "fk_{0}_user_id_users",
)


def rename(before: str, after: str) -> None:
    old, new = f"team_season_{before}", f"team_season_{after}"
    op.rename_table(old, new)
    for column in INDEXED:
        op.drop_index(f"ix_{old}_{column}", table_name=new)
        op.create_index(f"ix_{new}_{column}", new, [column], unique=False)
    if op.get_bind().dialect.name == "postgresql":
        # Postgres alone names constraints in its catalogue and holds the enum labels
        for pattern in CONSTRAINTS:
            op.execute(
                f"ALTER TABLE {new} RENAME CONSTRAINT "
                f"{pattern.format(old)} TO {pattern.format(new)}"
            )
        # The label carries the stored value, so renaming it moves every row
        op.execute(f"ALTER TYPE rolekind RENAME VALUE '{before}' TO '{after}'")
    else:
        op.execute(
            f"UPDATE discord_role_binding SET kind = '{after}' WHERE kind = '{before}'"
        )


def upgrade() -> None:
    rename("coach", "captain")


def downgrade() -> None:
    rename("captain", "coach")
