"""Promote the week map to season rounds

A season is a list of rounds. Each round carries the window it is played
in, a start date and an optional end date, and the map of game 1, which
used to be the only per-playday setting and lived in season_week_map. Every
season gets one row per playday, a week long, a week apart from its start date.

Revision ID: e6f1a9c3d5b7
Revises: d5e8f1a2b3c4
Create Date: 2026-09-07 12:00:00.000000

"""

from collections.abc import Sequence
from datetime import date, timedelta

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e6f1a9c3d5b7"
down_revision: str | Sequence[str] | None = "d5e8f1a2b3c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROUNDS = "season_rounds"
WEEK_MAP = "season_week_map"


def upgrade() -> None:
    op.create_table(
        ROUNDS,
        sa.Column("season_id", sa.Integer(), nullable=False),
        sa.Column("playday", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("map_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["map_id"], ["maps.id"], name=op.f("fk_season_rounds_map_id_maps")
        ),
        sa.ForeignKeyConstraint(
            ["season_id"],
            ["seasons.id"],
            name=op.f("fk_season_rounds_season_id_seasons"),
        ),
        sa.PrimaryKeyConstraint("season_id", "playday", name=op.f("pk_season_rounds")),
    )
    op.create_index(op.f("ix_season_rounds_map_id"), ROUNDS, ["map_id"], unique=False)
    op.execute(
        f"INSERT INTO {ROUNDS} (season_id, playday, map_id) "
        f"SELECT season_id, playday, map_id FROM {WEEK_MAP}"
    )
    op.drop_index(op.f("ix_season_week_map_map_id"), table_name=WEEK_MAP)
    op.drop_table(WEEK_MAP)

    # One round per playday of every season, a week apart from its start date
    bind = op.get_bind()
    have = {
        (season_id, playday)
        for season_id, playday in bind.execute(
            sa.text(f"SELECT season_id, playday FROM {ROUNDS}")
        )
    }
    seasons = bind.execute(
        sa.text("SELECT id, number_weeks, start_date FROM seasons")
    ).all()
    for season_id, number_weeks, start in seasons:
        if isinstance(start, str):
            start = date.fromisoformat(start)
        for playday in range(1, (number_weeks or 0) + 1):
            starts = start + timedelta(weeks=playday - 1) if start else None
            ends = starts + timedelta(days=6) if starts else None
            if (season_id, playday) in have:
                statement = (
                    f"UPDATE {ROUNDS} SET start_date = :start, end_date = :end "
                    "WHERE season_id = :season_id AND playday = :playday"
                )
            else:
                statement = (
                    f"INSERT INTO {ROUNDS} (season_id, playday, start_date, end_date) "
                    "VALUES (:season_id, :playday, :start, :end)"
                )
            bind.execute(
                sa.text(statement),
                {
                    "season_id": season_id,
                    "playday": playday,
                    "start": starts,
                    "end": ends,
                },
            )


def downgrade() -> None:
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
    op.create_index(op.f("ix_season_week_map_map_id"), WEEK_MAP, ["map_id"])
    # The dates are lost; only the rounds with a map go back
    op.execute(
        f"INSERT INTO {WEEK_MAP} (season_id, playday, map_id) "
        f"SELECT season_id, playday, map_id FROM {ROUNDS} WHERE map_id IS NOT NULL"
    )
    op.drop_index(op.f("ix_season_rounds_map_id"), table_name=ROUNDS)
    op.drop_table(ROUNDS)
