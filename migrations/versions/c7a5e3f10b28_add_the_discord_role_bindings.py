"""Bind every app-owned Discord role in one table

A team held its role in a column and the coach role sat in a settings row, so
nothing else could be mirrored. One binding table holds them all, and the
upgrade seeds it from both places before the column goes. The downgrade puts
the team roles back in the column and drops the table.

Revision ID: c7a5e3f10b28
Revises: b3f9d7c21a48
Create Date: 2026-08-30 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7a5e3f10b28"
down_revision: str | Sequence[str] | None = "b3f9d7c21a48"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KINDS = ("coach", "team", "fantasy", "gnl_participant", "champion")

kind = sa.Enum(*KINDS, name="rolekind")

bindings = sa.table(
    "discord_role_binding",
    sa.column("kind", kind),
    sa.column("season_id", sa.Integer),
    sa.column("team_id", sa.Integer),
    sa.column("discord_role", sa.String),
)


def upgrade() -> None:
    op.create_table(
        "discord_role_binding",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", kind, nullable=False),
        sa.Column("season_id", sa.Integer(), nullable=True),
        sa.Column("team_id", sa.Integer(), nullable=True),
        sa.Column(
            "discord_role", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["season_id"],
            ["seasons.id"],
            name=op.f("fk_discord_role_binding_season_id_seasons"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
            name=op.f("fk_discord_role_binding_team_id_teams"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_discord_role_binding")),
    )
    op.create_index(
        op.f("ix_discord_role_binding_season_id"),
        "discord_role_binding",
        ["season_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_discord_role_binding_team_id"),
        "discord_role_binding",
        ["team_id"],
        unique=False,
    )
    op.create_index(
        "uq_discord_role_binding_discord_role",
        "discord_role_binding",
        ["discord_role"],
        unique=True,
    )

    bind = op.get_bind()
    # The admin role stays a settings row: login reads it, sync never writes it
    coach = bind.scalar(
        sa.text("SELECT value FROM settings WHERE key = 'captain_coach_role'")
    )
    # Every row carries every column: bulk_insert reads the keys of the first
    rows = (
        [{"kind": "coach", "season_id": None, "team_id": None, "discord_role": coach}]
        if coach
        else []
    )
    rows += [
        {
            "kind": "team",
            "season_id": None,
            "team_id": team.id,
            "discord_role": team.discord_role,
        }
        for team in bind.execute(
            sa.text("SELECT id, discord_role FROM teams WHERE discord_role IS NOT NULL")
        )
    ]
    if rows:
        op.bulk_insert(bindings, rows)

    op.drop_index("uq_teams_discord_role", table_name="teams")
    op.drop_column("teams", "discord_role")


def downgrade() -> None:
    op.add_column(
        "teams",
        sa.Column(
            "discord_role", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=True
        ),
    )
    bind = op.get_bind()
    for row in bind.execute(
        sa.select(bindings).where(
            bindings.c.kind == "team", bindings.c.team_id.isnot(None)
        )
    ):
        bind.execute(
            sa.text("UPDATE teams SET discord_role = :role WHERE id = :id"),
            {"role": row.discord_role, "id": row.team_id},
        )
    op.execute("CREATE UNIQUE INDEX uq_teams_discord_role ON teams (discord_role)")

    op.drop_index(
        "uq_discord_role_binding_discord_role", table_name="discord_role_binding"
    )
    op.drop_index(
        op.f("ix_discord_role_binding_team_id"), table_name="discord_role_binding"
    )
    op.drop_index(
        op.f("ix_discord_role_binding_season_id"), table_name="discord_role_binding"
    )
    op.drop_table("discord_role_binding")
    # Postgres keeps the enum type after the table goes; SQLite has none
    kind.drop(bind, checkfirst=True)
