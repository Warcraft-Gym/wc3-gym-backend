from typing import Annotated, Any, Self

from sqlalchemy import Index
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.interfaces import ORMOption
from sqlmodel import Field, Relationship, SQLModel

from app.core.db import rel
from app.models.base import DBModel, ident
from app.models.match import Match
from app.models.relationships import DBMapSeason, DBUserSeasonSignup
from app.models.season import Season, SeasonPublic
from app.models.series import Series, SeriesPublic
from app.models.types import EmptyStrToNone
from app.models.user import User, UserPublic


class FantasyBetBase(SQLModel):
    season_id: int = Field(index=True, foreign_key="seasons.id", ondelete="CASCADE")
    series_id: int = Field(index=True, foreign_key="series.id", ondelete="CASCADE")
    user_id: int = Field(index=True, foreign_key="users.id", ondelete="CASCADE")
    winner_id: int = Field(index=True, foreign_key="users.id", ondelete="CASCADE")


class FantasyBet(FantasyBetBase, DBModel, table=True):
    __tablename__ = "fantasy_bets"
    # A bettor picks one player to win a series, so a second bet is a repeat
    __table_args__ = (
        Index("uq_fantasy_bets_series_id_user_id", "series_id", "user_id", unique=True),
    )

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
    def eager_options(cls) -> tuple[ORMOption, ...]:
        """Every relation the public bet reads."""
        # A bet holds four users: both sides of the bet and both players
        players = (
            joinedload(rel(cls.user)),
            joinedload(rel(cls.winner)),
            joinedload(rel(cls.series)).joinedload(rel(Series.player1)),
            joinedload(rel(cls.series)).joinedload(rel(Series.player2)),
        )
        return (
            # Collections use selectinload; a joined collection multiplies the rows
            joinedload(rel(cls.season))
            .selectinload(rel(Season.maps))
            .joinedload(rel(DBMapSeason.map)),
            joinedload(rel(cls.series))
            .joinedload(rel(Series.match))
            .joinedload(rel(Match.team1)),
            joinedload(rel(cls.series))
            .joinedload(rel(Series.match))
            .joinedload(rel(Match.team2)),
            joinedload(rel(cls.series))
            .joinedload(rel(Series.match))
            .joinedload(rel(Match.season)),
            joinedload(rel(cls.series))
            .joinedload(rel(Series.match))
            .joinedload(rel(Match.fixed_map)),
            *(
                option
                for player in players
                for option in (
                    player.selectinload(rel(User.w3c_stats)),
                    player.selectinload(rel(User.team_seasons)),
                    player.selectinload(rel(User.signup_seasons)).joinedload(
                        rel(DBUserSeasonSignup.season)
                    ),
                )
            ),
        )

    @classmethod
    def list_eager_options(cls) -> tuple[ORMOption, ...]:
        """The to-one relations the reduced public bet reads."""
        return (
            joinedload(rel(cls.season)),
            joinedload(rel(cls.user)),
            joinedload(rel(cls.winner)),
            joinedload(rel(cls.series)).joinedload(rel(Series.player1)),
            joinedload(rel(cls.series)).joinedload(rel(Series.player2)),
            joinedload(rel(cls.series))
            .joinedload(rel(Series.match))
            .joinedload(rel(Match.team1)),
            joinedload(rel(cls.series))
            .joinedload(rel(Series.match))
            .joinedload(rel(Match.team2)),
            joinedload(rel(cls.series))
            .joinedload(rel(Series.match))
            .joinedload(rel(Match.season)),
            joinedload(rel(cls.series))
            .joinedload(rel(Series.match))
            .joinedload(rel(Match.fixed_map)),
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


class FantasyBetPublic(FantasyBetBase):
    # app.services.derived.fill_bet_results answers this one; no column holds it
    bet_result: int | None = None
    id: int
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
    def from_fantasy_bet(cls, fbet: FantasyBet) -> Self:
        return cls(
            id=ident(fbet),
            series_id=fbet.series_id,
            season_id=fbet.season_id,
            season=SeasonPublic.from_season(fbet.season) if fbet.season else None,
            series=SeriesPublic.from_series(fbet.series) if fbet.series else None,
            user_id=fbet.user_id,
            user=UserPublic.from_user(fbet.user) if fbet.user else None,
            winner_id=fbet.winner_id,
            winner=UserPublic.from_user(fbet.winner) if fbet.winner else None,
            bet_points=fbet.bet_points,
        )

    @classmethod
    def from_fantasy_bet_reduced(cls, fbet: FantasyBet) -> Self:
        """Every field of the bet, with the nested collections empty."""
        return cls(
            id=ident(fbet),
            series_id=fbet.series_id,
            season_id=fbet.season_id,
            season=SeasonPublic.from_season_without_maps(fbet.season)
            if fbet.season
            else None,
            series=SeriesPublic.from_series_reduced(fbet.series)
            if fbet.series
            else None,
            user_id=fbet.user_id,
            user=UserPublic.from_user_reduced(fbet.user) if fbet.user else None,
            winner_id=fbet.winner_id,
            winner=UserPublic.from_user_reduced(fbet.winner) if fbet.winner else None,
            bet_points=fbet.bet_points,
        )

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
