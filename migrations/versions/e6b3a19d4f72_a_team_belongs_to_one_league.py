"""A team belongs to one league

The roster and captains belong to an event, but the team identity belongs to
the league whose events it enters. Existing teams are backfilled from their
events. Legacy unattached teams belong to the GNL, which was the only team
league before leagues were modelled.

Revision ID: e6b3a19d4f72
Revises: a4f1c7b92e05
Create Date: 2026-09-15 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e6b3a19d4f72"
down_revision: str | Sequence[str] | None = "a4f1c7b92e05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    op.add_column("teams", sa.Column("league_id", sa.Integer(), nullable=True))

    # A team reaches an event through its season link or as an event entrant
    links = (
        "SELECT ts.team_id AS team_id, e.league_id AS league_id "
        "FROM team_season ts JOIN event e ON e.id = ts.season_id "
        "UNION "
        "SELECT ee.team_id AS team_id, e.league_id AS league_id "
        "FROM event_entrant ee JOIN event e ON e.id = ee.event_id "
        "WHERE ee.team_id IS NOT NULL"
    )

    # A team linked to events of two leagues has no unambiguous owner. Refuse
    # that data rather than silently assigning the first league we happen to read.
    conflicted = bind.execute(
        sa.text(
            f"SELECT link.team_id FROM ({links}) link "
            "GROUP BY link.team_id HAVING COUNT(DISTINCT link.league_id) > 1"
        )
    ).first()
    if conflicted:
        raise RuntimeError(
            f"Team {conflicted.team_id} is linked to events in more than one league"
        )

    op.execute(
        "UPDATE teams SET league_id = ("
        f"SELECT MIN(link.league_id) FROM ({links}) link "
        "WHERE link.team_id = teams.id"
        ")"
    )
    op.execute(
        "UPDATE teams SET league_id = (SELECT id FROM league WHERE kind = 'gnl' LIMIT 1) "
        "WHERE league_id IS NULL"
    )

    missing = bind.execute(
        sa.text("SELECT id FROM teams WHERE league_id IS NULL LIMIT 1")
    ).first()
    if missing:
        raise RuntimeError(
            f"Team {missing.id} has no event league and no GNL league exists"
        )

    with op.batch_alter_table("teams") as batch:
        batch.alter_column("league_id", existing_type=sa.Integer(), nullable=False)
        batch.create_foreign_key(
            op.f("fk_teams_league_id_league"), "league", ["league_id"], ["id"]
        )
        batch.create_index(op.f("ix_teams_league_id"), ["league_id"])


def downgrade() -> None:
    with op.batch_alter_table("teams") as batch:
        batch.drop_index(op.f("ix_teams_league_id"))
        batch.drop_constraint(op.f("fk_teams_league_id_league"), type_="foreignkey")
        batch.drop_column("league_id")
