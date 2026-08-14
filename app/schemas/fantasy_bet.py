from typing import Annotated

from app.schemas.base import APISchema, EmptyStrToNone
from app.schemas.season import Season
from app.schemas.series import Series
from app.schemas.user import User

DB_FIELDS = {
    "series_id",
    "season_id",
    "user_id",
    "winner_id",
    "bet_points",
    "bet_result",
}


class FantasyBet(APISchema):
    id: int | None = None
    series_id: int | None = None
    series: Series | None = None
    season_id: int | None = None
    season: Season | None = None
    user_id: int | None = None
    user: User | None = None
    winner_id: int | None = None
    winner: User | None = None
    # With fixed bet points enabled, the service overwrites this after
    # construction, so a cleared input from the UI must not fail here.
    bet_points: Annotated[int | None, EmptyStrToNone] = None
    bet_result: int | None = None

    def to_db_dict(self):
        return self.model_dump(include=DB_FIELDS)

    @classmethod
    def from_dbfantasybet(cls, fbet):
        if not fbet:
            return None

        return cls(
            id=fbet.id,
            series_id=fbet.series_id,
            season_id=fbet.season_id,
            season=Season.from_dbseason(fbet.season) if fbet.season else None,
            series=Series.from_dbseries(fbet.series) if fbet.series else None,
            user_id=fbet.user_id,
            user=User.from_dbuser(fbet.user) if fbet.user else None,
            winner_id=fbet.winner_id,
            winner=User.from_dbuser(fbet.winner) if fbet.winner else None,
            bet_points=fbet.bet_points,
            bet_result=fbet.bet_result,
        )

    @staticmethod
    def schema():
        return {
            "type": "object",
            "properties": {
                "series_id": {"type": "integer"},
                "user_id": {"type": "integer"},
                "winner_id": {"type": "integer"},
                "bet_score": {"type": "integer"},
                "bet_result": {"type": "integer"},
            },
            "required": ["series_id", "user_id", "winner_id", "bet_score"],
        }
