"""Move the caster into a series_cast table

A series_cast row names the series, the account that claimed it and the
channel it streams on. Every stored caster name becomes a row with no
account and a Twitch channel link, then the series and draft_series
columns go.

Revision ID: a9c4e7d1f2b3
Revises: d5e0f3a8b2c4
Create Date: 2026-09-07 00:00:00.000000

"""

import re
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a9c4e7d1f2b3"
down_revision: str | Sequence[str] | None = "d5e0f3a8b2c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def twitch_url(caster: str) -> str | None:
    """The channel link of a stored name; a name, a link or an @handle, any case."""
    login = re.sub(
        r"^(https?://)?(www\.)?(twitch\.tv/)?@?",
        "",
        caster.strip(),
        flags=re.IGNORECASE,
    )
    login = login.strip("/ ").lower()
    return f"https://www.twitch.tv/{login}" if login else None


def upgrade() -> None:
    op.create_table(
        "series_cast",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("series_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column(
            "channel_url", sqlmodel.sql.sqltypes.AutoString(length=200), nullable=False
        ),
        sa.Column(
            "vod_url", sqlmodel.sql.sqltypes.AutoString(length=300), nullable=True
        ),
        sa.Column("vod_added_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["series_id"],
            ["series.id"],
            name=op.f("fk_series_cast_series_id_series"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_series_cast_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_series_cast")),
        sa.UniqueConstraint(
            "series_id", "user_id", name=op.f("uq_series_cast_series_id")
        ),
    )
    op.create_index(op.f("ix_series_cast_series_id"), "series_cast", ["series_id"])

    bind = op.get_bind()
    stored = bind.execute(
        sa.text("SELECT id, caster FROM series WHERE caster IS NOT NULL")
    ).all()
    rows = [
        {"series_id": series_id, "channel_url": url, "created_at": datetime.now(UTC)}
        for series_id, caster in stored
        if (url := twitch_url(caster))
    ]
    if rows:
        bind.execute(
            sa.text(
                "INSERT INTO series_cast (series_id, channel_url, created_at) "
                "VALUES (:series_id, :channel_url, :created_at)"
            ),
            rows,
        )
    op.drop_column("series", "caster")
    op.drop_column("draft_series", "caster")


def downgrade() -> None:
    op.add_column("draft_series", sa.Column("caster", sa.String(50)))
    op.add_column("series", sa.Column("caster", sa.String(50)))
    # The first cast's Twitch login goes back on the row; the others are lost
    bind = op.get_bind()
    casts = bind.execute(
        sa.text("SELECT series_id, channel_url FROM series_cast ORDER BY id DESC")
    ).all()
    for series_id, url in casts:
        login = re.sub(r"^https?://(www\.)?twitch\.tv/", "", url)[:50]
        bind.execute(
            sa.text("UPDATE series SET caster = :login WHERE id = :id"),
            {"login": login, "id": series_id},
        )
    op.drop_index(op.f("ix_series_cast_series_id"), "series_cast")
    op.drop_table("series_cast")
