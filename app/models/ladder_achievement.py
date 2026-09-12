"""What one season pays for one achievement rule.

The rule itself is code: `core.achievements` holds the condition, the name,
the description and the icon, keyed by a stable `rule_id`. A row here is an
INSTANCE of that rule — which season pays it, and how much. Two seasons run
the same rule as two rows, so re-pricing one leaves the other alone, and a
season can drop a rule by having no row for it.

A row with no season is scored over the player's whole history rather than
one season.
"""

from typing import Annotated

from pydantic import model_validator
from sqlalchemy import JSON, Index, text
from sqlmodel import Field, SQLModel

from app.models.base import DBModel


class LadderAchievementBase(SQLModel):
    # No season means the rule is lifetime, read over every match of the player
    season_id: int | None = Field(
        default=None, foreign_key="event.id", ondelete="CASCADE"
    )
    # The id of a rule in core.achievements; a row naming no rule pays nothing
    rule_id: str = Field(max_length=40)
    points: int
    # The rule's numbers this row overrides, `{}` for the rule's defaults
    params: dict[str, int] = Field(default_factory=dict, sa_type=JSON)


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


class SeasonAchievementWrite(SQLModel):
    """One row of a season's set, as the admin page sends it."""

    rule_id: str = Field(max_length=40)
    points: int = Field(ge=0)
    # The rule's numbers; a key the rule does not read is rejected
    params: dict[str, Annotated[int, Field(ge=1)]] = {}

    @model_validator(mode="after")
    def _rule_reads_every_key(self) -> "SeasonAchievementWrite":
        from app.core.achievements import BY_ID

        rule = BY_ID.get(self.rule_id)
        if rule is None:
            raise ValueError(f"No rule {self.rule_id}")
        unknown = sorted(self.params.keys() - rule.params.keys())
        if unknown:
            raise ValueError(f"{self.rule_id} reads no {', '.join(unknown)}")
        return self


class SeasonAchievementPublic(SQLModel):
    """A rule as one scope pays it: the catalogue text, the scope's price and
    numbers. `description` keeps its `{key}` placeholders for the editor."""

    rule_id: str
    name: str
    description: str
    icon: str
    team: bool
    points: int
    params: dict[str, int]

    @classmethod
    def of(
        cls, rule_id: str, points: int, params: dict[str, int] | None = None
    ) -> "SeasonAchievementPublic":
        from app.core.achievements import BY_ID, TEAM_IDS

        rule = BY_ID[rule_id]
        return cls(
            rule_id=rule.id,
            name=rule.name,
            description=rule.description,
            icon=rule.icon,
            team=rule.id in TEAM_IDS,
            points=points,
            params={**rule.params, **(params or {})},
        )


def catalogue() -> list[SeasonAchievementPublic]:
    """Every rule at its catalogue price and numbers."""
    from app.core.achievements import ACHIEVEMENTS

    return [SeasonAchievementPublic.of(rule.id, rule.points) for rule in ACHIEVEMENTS]


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
