"""Delete a season with every row under it

The event is the root of what a season holds. Every key that points at an
event now cascades, and so do the two keys below it that pointed at a row
the event already cascades to: a draft pairing at its fixture, and a drafted
player at their fantasy team.

Revision ID: d2a8f5c1e736
Revises: 55ae9f9d1db6
Create Date: 2026-10-05 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d2a8f5c1e736"
down_revision: str | Sequence[str] | None = "55ae9f9d1db6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# table, column, referred table
KEYS = [
    ("user_season_signup", "season_id", "event"),
    ("team_season_captain", "season_id", "event"),
    ("map_season", "season_id", "event"),
    ("event_round", "season_id", "event"),
    ("round_availability", "season_id", "event"),
    ("team_season", "season_id", "event"),
    ("user_team_season", "season_id", "event"),
    ("draft_series", "match_id", "matches"),
    ("fantasy_team_player", "fantasy_team_id", "fantasy_teams"),
]
# Several keys were created without a name, or under the table's old name;
# SQLite reflects none, so the convention names them for the batch
CONVENTION = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}


def _current_name(table: str, column: str, referred: str) -> str:
    for fk in sa.inspect(op.get_bind()).get_foreign_keys(table):
        if fk["constrained_columns"] == [column]:
            return fk["name"] or f"fk_{table}_{column}_{fk['referred_table']}"
    raise RuntimeError(f"{table}.{column} has no foreign key")


def _repoint(ondelete: str | None) -> None:
    for table, column, referred in KEYS:
        name = _current_name(table, column, referred)
        with op.batch_alter_table(table, naming_convention=CONVENTION) as batch:
            batch.drop_constraint(name, type_="foreignkey")
            batch.create_foreign_key(
                op.f(f"fk_{table}_{column}_{referred}"),
                referred,
                [column],
                ["id"],
                ondelete=ondelete,
            )


def upgrade() -> None:
    _repoint("CASCADE")


def downgrade() -> None:
    _repoint(None)
