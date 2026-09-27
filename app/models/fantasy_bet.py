from typing import Self

from sqlalchemy import Index
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.orm.interfaces import ORMOption
from sqlmodel import Field, Relationship, SQLModel

from app.core.db import rel
from app.models.base import DBModel, PublicModel, ident
from app.models.season import Season, SeasonSummaryPublic
from app.models.series import Series, SeriesPublic
from app.models.user import User, UserSummaryPublic


class FantasyBetBase(SQLModel):
    season_id: int = Field(index=True, foreign_key="event.id", ondelete="CASCADE")
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
        sa_relationship_kwargs={
            "lazy": "raise_on_sql",
            "foreign_keys": "[FantasyBet.season_id]",
        }
    )
    series: "Series" = Relationship(
        sa_relationship_kwargs={
            "lazy": "raise_on_sql",
            "foreign_keys": "[FantasyBet.series_id]",
        }
    )
    user: "User" = Relationship(
        sa_relationship_kwargs={
            "lazy": "raise_on_sql",
            "foreign_keys": "[FantasyBet.user_id]",
        }
    )
    winner: "User" = Relationship(
        sa_relationship_kwargs={
            "lazy": "raise_on_sql",
            "foreign_keys": "[FantasyBet.winner_id]",
        }
    )

    @classmethod
    def loads(cls) -> tuple[ORMOption, ...]:
        """The rows a bet answer reads off the bet: its season, its bettor and
        winner bare, and its series as the series list row. A season and a
        series are each shared by many bets of a page, so selectin reads every
        distinct row once, not once per bet."""
        return (
            selectinload(rel(cls.season)),
            joinedload(rel(cls.user)),
            joinedload(rel(cls.winner)),
            selectinload(rel(cls.series)).options(
                *Series._list_eager_options(picks_only=True)
            ),
        )


class FantasyBetCreate(FantasyBetBase):
    # NOT NULL in the database; the service fills it in for fixed bet points
    bet_points: int | None = None


class FantasyBetUpdate(SQLModel):
    season_id: int | None = None
    series_id: int | None = None
    user_id: int | None = None
    winner_id: int | None = None
    bet_points: int | None = None


class PublicFantasyBetWrite(SQLModel):
    """A bet placed or edited from the public page; the session names the bettor.

    The season is the series' own, so the body never names it. An update keeps
    whatever field the body leaves out, so read it unset-aware.
    """

    series_id: int | None = None
    winner_id: int | None = None
    bet_points: int | None = None


class FantasyBetPublic(FantasyBetBase, PublicModel):
    # app.services.derived.fill_bet_results answers this one; no column holds it
    bet_result: int | None = None
    id: int
    season_id: int | None = None
    series_id: int | None = None
    user_id: int | None = None
    winner_id: int | None = None
    bet_points: int | None = None
    season: SeasonSummaryPublic | None = None
    series: SeriesPublic | None = None
    user: UserSummaryPublic | None = None
    winner: UserSummaryPublic | None = None

    @classmethod
    def from_fantasy_bet(cls, fbet: FantasyBet) -> Self:
        """The bet; its players carry their record in its season where the
        read loaded it."""
        return cls(
            id=ident(fbet),
            series_id=fbet.series_id,
            season_id=fbet.season_id,
            season=SeasonSummaryPublic.from_season(fbet.season)
            if fbet.season
            else None,
            series=SeriesPublic.from_series(fbet.series, fbet.season_id)
            if fbet.series
            else None,
            user_id=fbet.user_id,
            user=UserSummaryPublic.from_user(fbet.user, fbet.season_id)
            if fbet.user
            else None,
            winner_id=fbet.winner_id,
            winner=UserSummaryPublic.from_user(fbet.winner, fbet.season_id)
            if fbet.winner
            else None,
            bet_points=fbet.bet_points,
        )
