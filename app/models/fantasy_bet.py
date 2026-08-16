from typing import Annotated, Any, Self

from sqlalchemy.orm import joinedload
from sqlalchemy.sql.base import ExecutableOption
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import DBModel
from app.models.match import Match
from app.models.relationships import DBMapSeason, DBUserSeasonSignup
from app.models.season import Season, SeasonPublic
from app.models.series import Series, SeriesPublic
from app.models.types import EmptyStrToNone
from app.models.user import User, UserPublic
from app.models.user_team_season import DBUserTeamSeason


class FantasyBetBase(SQLModel):
    season_id: int = Field(foreign_key="seasons.id", ondelete="CASCADE")
    series_id: int = Field(foreign_key="series.id", ondelete="CASCADE")
    user_id: int = Field(foreign_key="users.id", ondelete="CASCADE")
    winner_id: int = Field(foreign_key="users.id", ondelete="CASCADE")
    bet_result: int | None = None


class FantasyBet(FantasyBetBase, DBModel, table=True):
    __tablename__ = "fantasy_bets"

    id: int | None = Field(default=None, primary_key=True)
    bet_points: int

    season: "Season" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[FantasyBet.season_id]"}
    )
    series: "Series" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[FantasyBet.series_id]"}
    )
    user: "User" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[FantasyBet.user_id]"}
    )
    winner: "User" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[FantasyBet.winner_id]"}
    )

    @classmethod
    def eager_options(cls) -> tuple[ExecutableOption, ...]:
        """Every relation the public bet reads."""
        # A bet holds four users: both sides of the bet and both players
        players = (
            joinedload(cls.user),
            joinedload(cls.winner),
            joinedload(cls.series).joinedload(Series.player1),
            joinedload(cls.series).joinedload(Series.player2),
        )
        return (
            # Collections use selectinload; a joined collection multiplies the rows
            joinedload(cls.season)
            .selectinload(Season.maps)
            .joinedload(DBMapSeason.map),
            joinedload(cls.series).joinedload(Series.match).joinedload(Match.team1),
            joinedload(cls.series).joinedload(Series.match).joinedload(Match.team2),
            joinedload(cls.series).joinedload(Series.match).joinedload(Match.season),
            joinedload(cls.series).joinedload(Series.match).joinedload(Match.fixed_map),
            *(
                option
                for player in players
                for option in (
                    player.selectinload(User.w3c_stats),
                    player.selectinload(User.team_seasons).joinedload(
                        DBUserTeamSeason.team
                    ),
                    player.selectinload(User.team_seasons).joinedload(
                        DBUserTeamSeason.season
                    ),
                    player.selectinload(User.signup_seasons).joinedload(
                        DBUserSeasonSignup.season
                    ),
                )
            ),
        )


class FantasyBetCreate(FantasyBetBase):
    # NOT NULL in the database; the service fills it in for fixed bet points
    bet_points: Annotated[int | None, EmptyStrToNone] = None


class FantasyBetUpdate(SQLModel):
    season_id: int | None = None
    series_id: int | None = None
    user_id: int | None = None
    winner_id: int | None = None
    bet_points: Annotated[int | None, EmptyStrToNone] = None
    bet_result: int | None = None


class FantasyBetPublic(FantasyBetBase):
    id: int | None = None
    season_id: int | None = None
    series_id: int | None = None
    user_id: int | None = None
    winner_id: int | None = None
    bet_points: int | None = None
    season: SeasonPublic | None = None
    series: SeriesPublic | None = None
    user: UserPublic | None = None
    winner: UserPublic | None = None

    @classmethod
    def from_fantasy_bet(cls, fbet: FantasyBet | None) -> Self | None:
        if not fbet:
            return None

        return cls(
            id=fbet.id,
            series_id=fbet.series_id,
            season_id=fbet.season_id,
            season=SeasonPublic.from_season(fbet.season) if fbet.season else None,
            series=SeriesPublic.from_series(fbet.series) if fbet.series else None,
            user_id=fbet.user_id,
            user=UserPublic.from_user(fbet.user) if fbet.user else None,
            winner_id=fbet.winner_id,
            winner=UserPublic.from_user(fbet.winner) if fbet.winner else None,
            bet_points=fbet.bet_points,
            bet_result=fbet.bet_result,
        )

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
