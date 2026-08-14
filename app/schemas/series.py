from typing import Annotated

from app.schemas.base import APISchema, IsoDateTime, NumToStr
from app.schemas.match import Match
from app.schemas.user import User

DB_FIELDS = {
    "match_id",
    "date_time",
    "caster",
    "player1_id",
    "player2_id",
    "player1_score",
    "player2_score",
    "player1_points",
    "player2_points",
    "host_player_id",
    "is_fantasy_match",
}


class Series(APISchema):
    id: int | None = None
    match_id: int | None = None
    match: Match | None = None
    date_time: IsoDateTime | None = None
    caster: Annotated[str | None, NumToStr] = None
    player1_id: int | None = None
    player1: User | None = None
    player2_id: int | None = None
    player2: User | None = None
    player1_score: int | None = None
    player2_score: int | None = None
    player1_points: int | None = None
    player2_points: int | None = None
    host_player_id: int | None = None
    is_fantasy_match: bool | None = None

    def to_db_dict(self):
        return self.model_dump(include=DB_FIELDS)

    @classmethod
    def from_dbseries(cls, series):
        if not series:
            return None

        return cls(
            id=series.id,
            match_id=series.match_id,
            match=Match.from_dbmatch(series.match) if series.match else None,
            date_time=series.date_time,
            caster=series.caster,
            player1_id=series.player1_id,
            player1=User.from_dbuser(series.player1) if series.player1 else None,
            player2_id=series.player2_id,
            player2=User.from_dbuser(series.player2) if series.player2 else None,
            player1_score=series.player1_score,
            player2_score=series.player2_score,
            player1_points=series.player1_points,
            player2_points=series.player2_points,
            host_player_id=series.host_player_id,
            is_fantasy_match=series.is_fantasy_match,
        )
