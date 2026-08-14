from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship

from app.models.base import DBModel

if TYPE_CHECKING:
    from app.models.season import DBSeason
    from app.models.series import DBSeries
    from app.models.user import DBUser


class DBFantasyBet(DBModel, table=True):
    __tablename__ = "fantasy_bets"
    id: int | None = Field(default=None, primary_key=True)
    season_id: int = Field(foreign_key="seasons.id", ondelete="CASCADE")
    series_id: int = Field(foreign_key="series.id", ondelete="CASCADE")
    user_id: int = Field(foreign_key="users.id", ondelete="CASCADE")
    winner_id: int = Field(foreign_key="users.id", ondelete="CASCADE")
    bet_points: int
    bet_result: int | None = None

    season: "DBSeason" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[DBFantasyBet.season_id]"}
    )
    series: "DBSeries" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[DBFantasyBet.series_id]"}
    )
    user: "DBUser" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[DBFantasyBet.user_id]"}
    )
    winner: "DBUser" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[DBFantasyBet.winner_id]"}
    )

    def to_dict(self):
        return {
            column.name: getattr(self, column.name) for column in self.__table__.columns
        }
