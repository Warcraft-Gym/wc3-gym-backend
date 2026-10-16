"""The series a cup plays, in tables of their own: cup_series and its children.

A cup series hangs off a round of a cup's stage and names an entrant on each
side, or seats a free for all lobby. GNL and KOTH keep the `series` table, so
no GNL rule (captains, fixtures, replays, Discord cards) reads a cup row and
no cup rule reads a GNL one.

Side A is player1 and side B is player2, as on a GNL series. A team side
names no player: the rows of `cup_series_side` with its `side_no` are the
players it fields, and a lobby holds one such row per seat.
"""

from typing import Annotated, Any, Self

from sqlalchemy import false
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.strategy_options import _AbstractLoad
from sqlmodel import Field, Relationship, SQLModel, col

from app.core.db import rel
from app.models.base import DBModel, PublicModel, ident
from app.models.enums import Race
from app.models.event_entrant import EventEntrant
from app.models.map import Map
from app.models.relationships import EventRoundPublic
from app.models.series import SeriesRulesPublic
from app.models.series_side import SeriesSidePublic
from app.models.team_summary import TeamSummaryPublic
from app.models.types import EnumValue, SuggestRace
from app.models.user import User, UserSummaryPublic


class CupVetoStep(DBModel, table=True):
    """One step of a cup series' map veto, in the order the best-of names."""

    __tablename__ = "cup_veto_step"
    series_id: int = Field(
        foreign_key="cup_series.id", ondelete="CASCADE", primary_key=True
    )
    step_no: int = Field(primary_key=True)
    side: str = Field(max_length=1)
    action: str = Field(max_length=4)
    map_id: int = Field(foreign_key="maps.id")
    # Who typed the step in; null when the step took itself or a runner has no player row
    entered_by: int | None = Field(
        default=None, foreign_key="users.id", ondelete="SET NULL"
    )
    map: Map | None = Relationship()


class CupSeries(DBModel, table=True):
    __tablename__ = "cup_series"

    id: int | None = Field(default=None, primary_key=True)
    round_id: int = Field(index=True, foreign_key="event_round.id", ondelete="CASCADE")
    division_id: int | None = Field(
        default=None, foreign_key="event_division.id", ondelete="SET NULL"
    )
    # Where the series sits in its round
    sequence: int | None = None
    # The map a free for all lobby is played on, drawn from the cup's pool; a
    # two-sided series names its maps per game instead
    lobby_map_id: int | None = Field(
        default=None, foreign_key="maps.id", ondelete="SET NULL"
    )
    # The entrant on each side: a solo entrant also fills the player id below,
    # a team entrant leaves it null and its roster plays the side
    entrant1_id: int | None = Field(
        default=None, index=True, foreign_key="event_entrant.id", ondelete="SET NULL"
    )
    entrant2_id: int | None = Field(
        default=None, index=True, foreign_key="event_entrant.id", ondelete="SET NULL"
    )
    player1_id: int | None = Field(
        default=None, index=True, foreign_key="users.id", ondelete="CASCADE"
    )
    player2_id: int | None = Field(
        default=None, index=True, foreign_key="users.id", ondelete="CASCADE"
    )
    player1_score: int | None = None
    player2_score: int | None = None
    # played, walkover or forfeit
    result_kind: str = Field(
        default="played", max_length=10, sa_column_kwargs={"server_default": "played"}
    )
    # The race a side played when it is not the one it entered the cup on
    player1_off_race: Annotated[Race | None, SuggestRace] = None
    player2_off_race: Annotated[Race | None, SuggestRace] = None
    # How many players a side holds: 1 for a 1v1, 2 for a 2v2
    side_size: int = Field(default=1, sa_column_kwargs={"server_default": "1"})
    # The feeder graph: each slot takes the winner, or the loser, of one series
    slot1_from_series_id: int | None = Field(
        default=None, foreign_key="cup_series.id", ondelete="SET NULL"
    )
    slot1_takes_loser: bool = Field(
        default=False, sa_column_kwargs={"server_default": false()}
    )
    slot2_from_series_id: int | None = Field(
        default=None, foreign_key="cup_series.id", ondelete="SET NULL"
    )
    slot2_takes_loser: bool = Field(
        default=False, sa_column_kwargs={"server_default": false()}
    )
    entrant1: EventEntrant | None = Relationship(
        sa_relationship_kwargs={
            "lazy": "raise_on_sql",
            "foreign_keys": "[CupSeries.entrant1_id]",
        }
    )
    entrant2: EventEntrant | None = Relationship(
        sa_relationship_kwargs={
            "lazy": "raise_on_sql",
            "foreign_keys": "[CupSeries.entrant2_id]",
        }
    )
    player1: User | None = Relationship(
        sa_relationship_kwargs={
            "lazy": "raise_on_sql",
            "foreign_keys": "[CupSeries.player1_id]",
        }
    )
    player2: User | None = Relationship(
        sa_relationship_kwargs={
            "lazy": "raise_on_sql",
            "foreign_keys": "[CupSeries.player2_id]",
        }
    )
    veto_steps: list[CupVetoStep] = Relationship(
        sa_relationship_kwargs={"lazy": "raise_on_sql", "cascade": "all, delete-orphan"}
    )

    @classmethod
    def eager_options(cls) -> tuple[_AbstractLoad, ...]:
        """The rows a cup series box reads off the series: its entrants, its
        players and its two picks."""
        picks = rel(cls.veto_steps).and_(col(CupVetoStep.action) == "pick")
        return (
            selectinload(rel(cls.entrant1)),
            selectinload(rel(cls.entrant2)),
            selectinload(rel(cls.player1)),
            selectinload(rel(cls.player2)),
            selectinload(picks).selectinload(rel(CupVetoStep.map)),
        )


class CupSeriesGame(DBModel, table=True):
    """One game of a cup series: the side that won it and the map it was on."""

    __tablename__ = "cup_series_game"
    series_id: int = Field(
        foreign_key="cup_series.id", ondelete="CASCADE", primary_key=True
    )
    game_no: int = Field(primary_key=True)
    winner_side: str | None = Field(default=None, max_length=1)
    map_id: int | None = Field(default=None, foreign_key="maps.id", ondelete="SET NULL")


class CupSeriesSide(DBModel, table=True):
    """One seat of a lobby, or one player of a team side."""

    __tablename__ = "cup_series_side"

    series_id: int = Field(
        primary_key=True, foreign_key="cup_series.id", ondelete="CASCADE"
    )
    side_no: int = Field(primary_key=True)
    # A key column takes no null, so 0 says the seat names no player yet
    user_id: int = Field(
        default=0,
        primary_key=True,
        index=True,
        sa_column_kwargs={"server_default": "0"},
    )
    entrant_id: int | None = Field(
        default=None, foreign_key="event_entrant.id", ondelete="SET NULL"
    )
    # Where the side finished the series; every row of one side carries it
    place: int | None = None


def _pick_map(series: CupSeries, side: str) -> str | None:
    """The map one side picked in the veto, by name; null before the pick."""
    for step in series.veto_steps:
        if step.action == "pick" and step.side == side:
            return step.map.name if step.map else None
    return None


class CupSeriesSidePublic(SeriesSidePublic):
    """One seat of a cup lobby: a player, or in a team free for all the cup team
    in it with its players."""

    team: TeamSummaryPublic | None = None
    players: list[UserSummaryPublic] = []
    # The seat's entrant withdrew before the lobby was placed: no place, no next round
    left: bool = False


class LobbyMapPublic(SQLModel):
    """The map a lobby is played on."""

    id: int
    name: str


class LobbyMapWrite(SQLModel):
    """A runner's map for a lobby, one of the cup's pool."""

    map_id: int


class LobbyMoveWrite(SQLModel):
    """A runner's move of one entrant from a lobby to another lobby of its round."""

    entrant_id: int
    to_series_id: int


class CupSeriesPublic(PublicModel):
    """One cup series as its box and its report dialog read it."""

    id: int
    round_id: int
    sequence: int | None = None
    division_id: int | None = None
    entrant1_id: int | None = None
    entrant2_id: int | None = None
    player1_id: int | None = None
    player2_id: int | None = None
    player1: UserSummaryPublic | None = None
    player2: UserSummaryPublic | None = None
    player1_score: int | None = None
    player2_score: int | None = None
    result_kind: str = "played"
    # The off race a side reported, and null when it played its entry race
    player1_off_race: Annotated[str | None, EnumValue] = None
    player2_off_race: Annotated[str | None, EnumValue] = None
    # The race each side played: the off race, else the race it entered on
    player1_race: Annotated[str | None, EnumValue] = None
    player2_race: Annotated[str | None, EnumValue] = None
    # The map each side picked in the veto
    player1_pick_map: str | None = None
    player2_pick_map: str | None = None
    # The map rules and the best-of, from the round and the stage
    rules: SeriesRulesPublic | None = None
    # Each side's current MMR on the race the row names, else the MMR of the time
    player1_mmr: int | None = None
    player2_mmr: int | None = None
    # The team behind a side, so the box prints its name; null for a player
    team1: TeamSummaryPublic | None = None
    team2: TeamSummaryPublic | None = None
    side_size: int = 1
    # Every seat of a lobby, or every player of a team side, in side order
    sides: list[CupSeriesSidePublic] = []
    # The map a lobby is played on; null on a two-sided series
    lobby_map: LobbyMapPublic | None = None
    slot1_from_series_id: int | None = None
    slot1_takes_loser: bool = False
    slot2_from_series_id: int | None = None
    slot2_takes_loser: bool = False
    # Where a fed side comes from, such as "Loser of UB R1 M3"
    slot1_source: str | None = None
    slot2_source: str | None = None
    # The seed of each side; null when the cup hides its seeds from the reader
    entrant1_seed: int | None = None
    entrant2_seed: int | None = None
    # The places a placement bracket series' group plays for
    place_from: int | None = None
    place_to: int | None = None

    @classmethod
    def from_series(cls, series: CupSeries) -> Self:
        return cls(
            id=ident(series),
            round_id=series.round_id,
            sequence=series.sequence,
            division_id=series.division_id,
            entrant1_id=series.entrant1_id,
            entrant2_id=series.entrant2_id,
            player1_id=series.player1_id,
            player2_id=series.player2_id,
            player1=UserSummaryPublic.from_user(series.player1)
            if series.player1
            else None,
            player2=UserSummaryPublic.from_user(series.player2)
            if series.player2
            else None,
            player1_score=series.player1_score,
            player2_score=series.player2_score,
            result_kind=series.result_kind,
            player1_off_race=series.player1_off_race,
            player2_off_race=series.player2_off_race,
            player1_pick_map=_pick_map(series, "A"),
            player2_pick_map=_pick_map(series, "B"),
            side_size=series.side_size,
            slot1_from_series_id=series.slot1_from_series_id,
            slot1_takes_loser=series.slot1_takes_loser,
            slot2_from_series_id=series.slot2_from_series_id,
            slot2_takes_loser=series.slot2_takes_loser,
        )


class CupStagePublic(PublicModel):
    """The rounds of one cup stage and every series it holds, as the cup
    page draws them: a round names a bracket column, a series a box in it."""

    rounds: list[EventRoundPublic] = []
    series: list[CupSeriesPublic] = []


class MyCupSeriesPublic(PublicModel):
    """One cup series or lobby the caller still plays, as the home lists it:
    the cup, the stage and the round it sits in, and its box."""

    event_id: int
    event_name: str | None = None
    stage_id: int | None = None
    stage_name: str | None = None
    round_number: int
    round_name: str | None = None
    series: CupSeriesPublic


class CupScoreWrite(SQLModel):
    """A result a runner writes, or clears with two nulls."""

    player1_score: int | None = Field(default=None, ge=0)
    player2_score: int | None = Field(default=None, ge=0)
    player1_off_race: Annotated[Race | None, SuggestRace] = None
    player2_off_race: Annotated[Race | None, SuggestRace] = None


class CupReportWrite(SQLModel):
    """What a side reports for its own series: the score, the games, the races."""

    player1_score: int | None = None
    player2_score: int | None = None
    # An empty value clears the stored off race
    player1_off_race: str | None = None
    player2_off_race: str | None = None
    games: list[dict[str, Any]] | None = None
