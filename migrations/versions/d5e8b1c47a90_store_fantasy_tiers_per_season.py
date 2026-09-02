"""Store fantasy tiers per season

The tier moves off the global users column onto the season signup row, and a season
says how many tiers it cuts. set_fantasy_tiers nulls every other user's tier, so every
user holding one was in the last Apply's pool; the backfill finds the newest season
whose signups cover all of them and copies the tiers onto that season's rows. Seasons
that do not cover them keep null, and users.fantasy_tier stays until it is dropped.

Revision ID: d5e8b1c47a90
Revises: 7764c747da5d
Create Date: 2026-09-02 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5e8b1c47a90"
down_revision: str | Sequence[str] | None = "7764c747da5d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

users = sa.table(
    "users", sa.column("id", sa.Integer), sa.column("fantasy_tier", sa.Integer)
)
signups = sa.table(
    "user_season_signup",
    sa.column("user_id", sa.Integer),
    sa.column("season_id", sa.Integer),
    sa.column("fantasy_tier", sa.Integer),
)


def _target_season(bind: sa.Connection) -> int | None:
    """The season the last allocation wrote: the newest one signing up every tiered user."""
    tiered = set(
        bind.scalars(sa.select(users.c.id).where(users.c.fantasy_tier.is_not(None)))
    )
    if not tiered:
        return None
    by_season: dict[int, set[int]] = {}
    for season_id, user_id in bind.execute(
        sa.select(signups.c.season_id, signups.c.user_id)
    ):
        by_season.setdefault(season_id, set()).add(user_id)
    covering = [season for season, ids in by_season.items() if tiered <= ids]
    return max(covering) if covering else None


def upgrade() -> None:
    op.add_column(
        "seasons",
        sa.Column("fantasy_tiers", sa.Integer(), nullable=False, server_default="6"),
    )
    op.add_column(
        "user_season_signup", sa.Column("fantasy_tier", sa.Integer(), nullable=True)
    )

    bind = op.get_bind()
    target = _target_season(bind)
    if target is not None:
        tier_of = (
            sa.select(users.c.fantasy_tier)
            .where(users.c.id == signups.c.user_id)
            .scalar_subquery()
        )
        op.execute(
            signups.update()
            .where(signups.c.season_id == target)
            .values(fantasy_tier=tier_of)
        )


def downgrade() -> None:
    op.drop_column("user_season_signup", "fantasy_tier")
    op.drop_column("seasons", "fantasy_tiers")
