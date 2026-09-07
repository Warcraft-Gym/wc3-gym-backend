"""Drop the caster columns

series_cast holds every cast since a9c4e7d1f2b3, and the code that read
series.caster has shipped, so the two columns go. A downgrade puts the
first cast's Twitch login back on the series row.

Revision ID: b2d7f4e9c1a6
Revises: a9c4e7d1f2b3
Create Date: 2026-09-08 00:00:00.000000

"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2d7f4e9c1a6"
down_revision: str | Sequence[str] | None = "a9c4e7d1f2b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("series", "caster")
    op.drop_column("draft_series", "caster")


def downgrade() -> None:
    op.add_column("draft_series", sa.Column("caster", sa.String(50)))
    op.add_column("series", sa.Column("caster", sa.String(50)))
    bind = op.get_bind()
    # Oldest first, so the first cast of a series is the one that stays
    casts = bind.execute(
        sa.text("SELECT series_id, channel_url FROM series_cast ORDER BY id DESC")
    ).all()
    for series_id, url in casts:
        login = re.sub(r"^https?://(www\.)?twitch\.tv/", "", url)[:50]
        bind.execute(
            sa.text("UPDATE series SET caster = :login WHERE id = :id"),
            {"login": login, "id": series_id},
        )
