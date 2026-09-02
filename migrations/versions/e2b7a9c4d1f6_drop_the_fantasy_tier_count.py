"""Drop the fantasy tier count

A season's tier count is the number of cuts plus one, so the column is derived.
A season allocated before the cuts were stored gets its cuts rebuilt from the
tiers and the synced MMR: each cut is the lowest MMR of the tier above it, made
strictly ascending. A season whose players have no MMR keeps null.

Revision ID: e2b7a9c4d1f6
Revises: c4d1e7f9a2b3
Create Date: 2026-09-02 23:00:00.000000

"""

from collections.abc import Sequence
from itertools import pairwise

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2b7a9c4d1f6"
down_revision: str | Sequence[str] | None = "c4d1e7f9a2b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

seasons = sa.table(
    "seasons",
    sa.column("id", sa.Integer),
    sa.column("fantasy_tiers", sa.Integer),
    sa.column("fantasy_tier_cuts", sa.JSON),
)
signups = sa.table(
    "user_season_signup",
    sa.column("user_id", sa.Integer),
    sa.column("season_id", sa.Integer),
    sa.column("fantasy_tier", sa.Integer),
)
stats = sa.table(
    "w3cstats",
    sa.column("user_id", sa.Integer),
    sa.column("wc3_season", sa.Integer),
    sa.column("mmr", sa.Integer),
)


def rebuilt_cuts(count: int, tier_mmrs: dict[int, list[int]]) -> list[int] | None:
    """The cuts of an allocation: cut k opens tier count-k-1 at its lowest MMR."""
    if not any(tier_mmrs.values()):
        return None
    cuts: list[int] = []
    for tier in range(count - 1, 0, -1):
        floor = (cuts[-1] + 1) if cuts else 1
        cuts.append(max(floor, min(tier_mmrs.get(tier) or [floor])))
    return cuts


def upgrade() -> None:
    bind = op.get_bind()
    # Each user's MMR in their newest synced W3C season, the best of their races
    best: dict[int, tuple[int, int]] = {}
    for user_id, wc3_season, mmr in bind.execute(
        sa.select(stats.c.user_id, stats.c.wc3_season, stats.c.mmr).where(
            stats.c.mmr.is_not(None)
        )
    ):
        best[user_id] = max(best.get(user_id, (0, 0)), (wc3_season, mmr))
    for season_id, count in bind.execute(
        sa.select(seasons.c.id, seasons.c.fantasy_tiers).where(
            seasons.c.fantasy_tier_cuts.is_(None)
        )
    ):
        tier_mmrs: dict[int, list[int]] = {}
        for user_id, tier in bind.execute(
            sa.select(signups.c.user_id, signups.c.fantasy_tier).where(
                signups.c.season_id == season_id, signups.c.fantasy_tier.is_not(None)
            )
        ):
            if user_id in best:
                tier_mmrs.setdefault(tier, []).append(best[user_id][1])
        if tier_mmrs:
            op.execute(
                seasons.update()
                .where(seasons.c.id == season_id)
                .values(fantasy_tier_cuts=rebuilt_cuts(count, tier_mmrs))
            )
    op.drop_column("seasons", "fantasy_tiers")


def downgrade() -> None:
    op.add_column(
        "seasons",
        sa.Column("fantasy_tiers", sa.Integer(), nullable=False, server_default="6"),
    )
    bind = op.get_bind()
    for season_id, cuts in bind.execute(
        sa.select(seasons.c.id, seasons.c.fantasy_tier_cuts).where(
            seasons.c.fantasy_tier_cuts.is_not(None)
        )
    ):
        assert all(a < b for a, b in pairwise(cuts))
        op.execute(
            seasons.update()
            .where(seasons.c.id == season_id)
            .values(fantasy_tiers=len(cuts) + 1)
        )
