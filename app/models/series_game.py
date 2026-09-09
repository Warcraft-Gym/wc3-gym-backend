"""One game of a series: the series_game table.

A series is won over several games, and the score alone cannot say who won
which one: a 2-1 fits two orders. A row per game names the side that won it
and the map it was played on, so the record holds what the score drops.

Side A is player1 of the series and side B is player2, as the veto steps
name them. The map is null when nobody said which map was played.
"""

from sqlmodel import Field, SQLModel

from app.models.base import DBModel


class DBSeriesGame(DBModel, table=True):
    __tablename__ = "series_game"
    series_id: int = Field(
        foreign_key="series.id", ondelete="CASCADE", primary_key=True
    )
    # The games count from 1, in the order they were played
    game_no: int = Field(primary_key=True)
    winner_side: str = Field(max_length=1)
    map_id: int | None = Field(default=None, foreign_key="maps.id", ondelete="SET NULL")


class SeriesGamePublic(SQLModel):
    game_no: int
    winner_side: str
    map_id: int | None = None
    # Filled from the season's map rules when no map is stored for the game
    offered_map_id: int | None = None
