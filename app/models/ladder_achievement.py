"""What one season pays for one achievement rule.

The rule itself is code: `core.achievements` holds the condition, the name,
the description and the icon, keyed by a stable `rule_id`. A row here is an
INSTANCE of that rule — which season pays it, and how much. Two seasons run
the same rule as two rows, so re-pricing one leaves the other alone, and a
season can drop a rule by having no row for it.

A row with no season is scored over the player's whole history rather than
one season.
"""

from sqlalchemy import Index, text
from sqlmodel import Field, SQLModel

from app.models.base import DBModel


class LadderAchievementBase(SQLModel):
    # No season means the rule is lifetime, read over every match of the player
    season_id: int | None = Field(default=None, foreign_key="seasons.id")
    # The id of a rule in core.achievements; a row naming no rule pays nothing
    rule_id: str = Field(max_length=40)
    points: int


class LadderAchievement(LadderAchievementBase, DBModel, table=True):
    __tablename__ = "ladder_achievements"
    __table_args__ = (
        # A season pays a rule once. Postgres and SQLite both count NULLs as
        # distinct, so the lifetime rows need their own index to say the same.
        Index(
            "uq_ladder_achievements_season_rule",
            "season_id",
            "rule_id",
            unique=True,
        ),
        Index(
            "uq_ladder_achievements_lifetime_rule",
            "rule_id",
            unique=True,
            sqlite_where=text("season_id IS NULL"),
            postgresql_where=text("season_id IS NULL"),
        ),
    )

    id: int | None = Field(default=None, primary_key=True)


class LadderAchievementPublic(LadderAchievementBase):
    id: int


def default_rows(season_id: int | None) -> list["LadderAchievement"]:
    """A scope's instances of every rule in the catalogue, at catalogue prices.

    A season is created with these so it scores like the season before it;
    an admin then re-prices or removes rows without touching any other season.
    """
    from app.core import achievements

    return [
        LadderAchievement(season_id=season_id, rule_id=rule_id, points=points)
        for rule_id, points in achievements.DEFAULT_PAID.items()
    ]
