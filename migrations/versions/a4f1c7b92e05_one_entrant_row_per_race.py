"""One entrant row per race, and the stamp that closes a night

A player may now enter an event once per race, so the unique key of
`event_entrant` widens to (event_id, user_id, race) and the new
`event.multi_entry` switch says which events take the second row. Every KOTH
event opens it; every other event keeps one row per player.

`event.closed_at` is the stamp an admin sets when a night ends. A chain with
every series scored waits for it before it reads finished, because the admin
keeps naming series until he closes the night.

Revision ID: a4f1c7b92e05
Revises: e7d4b1c6a539
Create Date: 2026-09-15 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a4f1c7b92e05"
down_revision: str | Sequence[str] | None = "e7d4b1c6a539"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Plain ALTER TABLE: a batch rebuild of `event` rewrites its self key
    op.add_column(
        "event",
        sa.Column(
            "multi_entry", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "event", sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute("UPDATE event SET multi_entry = true WHERE kind = 'koth'")
    with op.batch_alter_table("event_entrant") as batch:
        batch.drop_constraint(op.f("uq_event_entrant_event_id"), type_="unique")
        batch.create_unique_constraint(
            op.f("uq_event_entrant_event_id_user_id_race"),
            ["event_id", "user_id", "race"],
        )


def downgrade() -> None:
    with op.batch_alter_table("event_entrant") as batch:
        batch.drop_constraint(
            op.f("uq_event_entrant_event_id_user_id_race"), type_="unique"
        )
        batch.create_unique_constraint(
            op.f("uq_event_entrant_event_id"), ["event_id", "user_id"]
        )
    op.drop_column("event", "closed_at")
    op.drop_column("event", "multi_entry")
