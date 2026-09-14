"""A series names its entrants

A side of a series is the entrant that plays it, so `series.entrant1_id` and
`entrant2_id` point at event_entrant beside the player ids. The player ids
stay: a solo entrant plays them and every GNL row keeps them, so the GNL
payloads are unchanged.

A pre-made team enters on no one race, so `event_entrant.race` turns
nullable, and a signup carries a note of what the entrant wants to work on.
`round_availability.answered_at` stamps when the answer was written, so a
round check-in reports its own time instead of the window's opening.

The backfill names the entrant of every series that plays in a round, from
the event of that round and the player on each side; a GNL series has no
round, so both of its entrant ids stay null.

Revision ID: b4e1c9a7d206
Revises: a3f7c05b2e91
Create Date: 2026-09-14 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b4e1c9a7d206"
down_revision: str | Sequence[str] | None = "a3f7c05b2e91"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RACES = ("RANDOM", "HU", "OC", "NE", "UD")
SIDES = ("entrant1_id", "entrant2_id")
# One statement per side: the entrant of the round's event that the player plays
BACKFILL = (
    "UPDATE series SET {side} = (SELECT e.id FROM event_entrant e, event_round r "
    "WHERE r.id = series.round_id AND e.event_id = r.season_id "
    "AND e.user_id = series.{player}) WHERE round_id IS NOT NULL"
)


def race_type() -> sa.Enum:
    """A reference to the race enum, which both databases already hold."""
    if op.get_bind().dialect.name == "postgresql":
        return postgresql.ENUM(*RACES, name="race", create_type=False)
    return sa.Enum(*RACES, name="race")


def upgrade() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"

    # The entrant of each side, beside the player ids the solo sides keep
    if sqlite:
        with op.batch_alter_table("series") as batch:
            for side in SIDES:
                batch.add_column(sa.Column(side, sa.Integer(), nullable=True))
                batch.create_foreign_key(
                    op.f(f"fk_series_{side}_event_entrant"),
                    "event_entrant",
                    [side],
                    ["id"],
                    ondelete="SET NULL",
                )
    else:
        for side in SIDES:
            op.add_column("series", sa.Column(side, sa.Integer(), nullable=True))
            op.create_foreign_key(
                op.f(f"fk_series_{side}_event_entrant"),
                "series",
                "event_entrant",
                [side],
                ["id"],
                ondelete="SET NULL",
            )
    for side in SIDES:
        op.create_index(op.f(f"ix_series_{side}"), "series", [side])
    for side, player in zip(SIDES, ("player1_id", "player2_id"), strict=True):
        op.execute(BACKFILL.format(side=side, player=player))

    # A team enters on no one race, and a signup says what it wants to work on
    if sqlite:
        with op.batch_alter_table("event_entrant") as batch:
            batch.add_column(sa.Column("note", sa.String(length=200), nullable=True))
            batch.alter_column("race", existing_type=race_type(), nullable=True)
    else:
        op.add_column(
            "event_entrant", sa.Column("note", sa.String(length=200), nullable=True)
        )
        op.alter_column(
            "event_entrant", "race", existing_type=race_type(), nullable=True
        )

    op.add_column(
        "round_availability",
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"

    op.drop_column("round_availability", "answered_at")

    # The old column takes no null, so a team row falls back to a random race
    op.execute("UPDATE event_entrant SET race = 'RANDOM' WHERE race IS NULL")
    if sqlite:
        with op.batch_alter_table("event_entrant") as batch:
            batch.alter_column("race", existing_type=race_type(), nullable=False)
            batch.drop_column("note")
    else:
        op.alter_column(
            "event_entrant", "race", existing_type=race_type(), nullable=False
        )
        op.drop_column("event_entrant", "note")

    for side in SIDES:
        op.drop_index(op.f(f"ix_series_{side}"), table_name="series")
    if sqlite:
        with op.batch_alter_table("series") as batch:
            for side in SIDES:
                batch.drop_constraint(
                    op.f(f"fk_series_{side}_event_entrant"), type_="foreignkey"
                )
                batch.drop_column(side)
    else:
        for side in SIDES:
            op.drop_constraint(
                op.f(f"fk_series_{side}_event_entrant"), "series", type_="foreignkey"
            )
            op.drop_column("series", side)
