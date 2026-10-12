"""Add the team cups: a team size, teams made for one cup, and their invites

A cup names how many players a team fields. A cup team is a team row made for
that one cup, with no league; its roster holds confirmed players only, and an
invited player waits in team_invite until they answer.

Revision ID: e7b4f2a9c5d1
Revises: d5a9c3e7b182
Create Date: 2026-10-08 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7b4f2a9c5d1"
down_revision: str | Sequence[str] | None = "d5a9c3e7b182"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("event", sa.Column("team_size", sa.Integer(), nullable=True))
    with op.batch_alter_table("teams") as batch:
        batch.alter_column("league_id", existing_type=sa.Integer(), nullable=True)
        batch.add_column(sa.Column("event_id", sa.Integer(), nullable=True))
        batch.create_index(op.f("ix_teams_event_id"), ["event_id"], unique=False)
        batch.create_foreign_key(
            op.f("fk_teams_event_id_event"),
            "event",
            ["event_id"],
            ["id"],
            ondelete="CASCADE",
        )
    op.create_table(
        "team_invite",
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("invited_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
            name=op.f("fk_team_invite_team_id_teams"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_team_invite_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["event.id"],
            name=op.f("fk_team_invite_event_id_event"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("team_id", "user_id", name=op.f("pk_team_invite")),
    )
    op.create_index(
        op.f("ix_team_invite_user_id"), "team_invite", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_team_invite_event_id"), "team_invite", ["event_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_team_invite_event_id"), table_name="team_invite")
    op.drop_index(op.f("ix_team_invite_user_id"), table_name="team_invite")
    op.drop_table("team_invite")
    # a cup team has no league to give back, so the cup teams go first
    op.execute("DELETE FROM teams WHERE event_id IS NOT NULL")
    with op.batch_alter_table("teams") as batch:
        batch.drop_constraint(op.f("fk_teams_event_id_event"), type_="foreignkey")
        batch.drop_index(op.f("ix_teams_event_id"))
        batch.drop_column("event_id")
        batch.alter_column("league_id", existing_type=sa.Integer(), nullable=False)
    op.drop_column("event", "team_size")
