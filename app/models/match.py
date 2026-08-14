from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship

from app.models.base import DBModel

if TYPE_CHECKING:
    from app.models.map import DBMap
    from app.models.season import DBSeason
    from app.models.team import DBTeam


class DBMatch(DBModel, table=True):
    __tablename__ = "matches"
    id: int | None = Field(default=None, primary_key=True)
    team1_id: int = Field(foreign_key="teams.id", ondelete="CASCADE")
    team2_id: int = Field(foreign_key="teams.id", ondelete="CASCADE")
    season_id: int = Field(foreign_key="seasons.id", ondelete="CASCADE")
    playday: int
    team1_score: int | None = None
    team2_score: int | None = None
    fixed_map_id: int | None = Field(default=None, foreign_key="maps.id")
    date_frame: str | None = Field(default=None, max_length=50)

    team1: "DBTeam" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[DBMatch.team1_id]"}
    )
    team2: "DBTeam" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[DBMatch.team2_id]"}
    )
    season: "DBSeason" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[DBMatch.season_id]"}
    )
    fixed_map: Optional["DBMap"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[DBMatch.fixed_map_id]"}
    )

    def to_dict(self):
        return {
            column.name: getattr(self, column.name) for column in self.__table__.columns
        }
