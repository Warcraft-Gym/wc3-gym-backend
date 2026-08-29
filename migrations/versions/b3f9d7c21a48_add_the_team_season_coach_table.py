"""Move the coaches of a team season into their own table

Three coach columns fixed the count at three. One row per coach lets a team
season carry any number. The upgrade copies the filled slots in and drops the
columns; the downgrade recreates them and puts the first three coaches back.

Revision ID: b3f9d7c21a48
Revises: 5f4a1a4d88d3
Create Date: 2026-08-30 10:00:00.000000

"""

from collections import defaultdict
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3f9d7c21a48"
down_revision: str | Sequence[str] | None = "5f4a1a4d88d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SLOTS = ("coach_1_id", "coach_2_id", "coach_3_id")

coaches = sa.table(
    "team_season_coach",
    sa.column("team_id", sa.Integer),
    sa.column("season_id", sa.Integer),
    sa.column("user_id", sa.Integer),
)


def upgrade() -> None:
    op.create_table(
        "team_season_coach",
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("season_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["season_id"],
            ["seasons.id"],
            name=op.f("fk_team_season_coach_season_id_seasons"),
        ),
        sa.ForeignKeyConstraint(
            ["team_id"], ["teams.id"], name=op.f("fk_team_season_coach_team_id_teams")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_team_season_coach_user_id_users")
        ),
        sa.PrimaryKeyConstraint(
            "team_id", "season_id", "user_id", name=op.f("pk_team_season_coach")
        ),
    )
    op.create_index(
        op.f("ix_team_season_coach_season_id"),
        "team_season_coach",
        ["season_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_team_season_coach_user_id"),
        "team_season_coach",
        ["user_id"],
        unique=False,
    )

    seats = op.get_bind().execute(
        sa.text(f"SELECT team_id, season_id, {', '.join(SLOTS)} FROM team_season")
    )
    rows = [
        {"team_id": seat.team_id, "season_id": seat.season_id, "user_id": user_id}
        for seat in seats
        # A user named in two slots is one coach, and the key holds him once
        for user_id in dict.fromkeys(
            filled for filled in (seat[2], seat[3], seat[4]) if filled
        )
    ]
    if rows:
        op.bulk_insert(coaches, rows)

    # Batch: SQLite drops neither an indexed column nor one a foreign key names
    with op.batch_alter_table("team_season") as batch:
        for slot in SLOTS:
            batch.drop_index(op.f(f"ix_team_season_{slot}"))
            batch.drop_column(slot)


def downgrade() -> None:
    with op.batch_alter_table("team_season") as batch:
        for slot in SLOTS:
            batch.add_column(sa.Column(slot, sa.Integer(), nullable=True))
            batch.create_index(op.f(f"ix_team_season_{slot}"), [slot])
            batch.create_foreign_key(
                op.f(f"fk_team_season_{slot}_users"), "users", [slot], ["id"]
            )

    bind = op.get_bind()
    by_season: dict[tuple[int, int], list[int]] = defaultdict(list)
    for row in bind.execute(
        sa.select(coaches).order_by(
            coaches.c.team_id, coaches.c.season_id, coaches.c.user_id
        )
    ):
        by_season[(row.team_id, row.season_id)].append(row.user_id)

    for (team_id, season_id), user_ids in by_season.items():
        # Three slots is all the old shape held
        slots = dict(zip(SLOTS, user_ids[:3], strict=False))
        bind.execute(
            sa.text(
                "UPDATE team_season SET "
                + ", ".join(f"{slot} = :{slot}" for slot in slots)
                + " WHERE team_id = :team_id AND season_id = :season_id"
            ),
            slots | {"team_id": team_id, "season_id": season_id},
        )

    op.drop_index(op.f("ix_team_season_coach_user_id"), table_name="team_season_coach")
    op.drop_index(
        op.f("ix_team_season_coach_season_id"), table_name="team_season_coach"
    )
    op.drop_table("team_season_coach")
