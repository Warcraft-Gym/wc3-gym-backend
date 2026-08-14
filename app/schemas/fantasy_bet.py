from typing import Annotated

from app.models.season import SeasonPublic
from app.models.series import SeriesPublic
from app.models.user import UserPublic
from app.schemas.base import APISchema, EmptyStrToNone

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
    series: SeriesPublic | None = None
    season_id: int | None = None
    season: SeasonPublic | None = None
    user_id: int | None = None
    user: UserPublic | None = None
    winner_id: int | None = None
    winner: UserPublic | None = None
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
            season=SeasonPublic.from_season(fbet.season) if fbet.season else None,
            series=SeriesPublic.from_series(fbet.series) if fbet.series else None,
            user_id=fbet.user_id,
            user=UserPublic.from_user(fbet.user) if fbet.user else None,
            winner_id=fbet.winner_id,
            winner=UserPublic.from_user(fbet.winner) if fbet.winner else None,
            bet_points=fbet.bet_points,
            bet_result=fbet.bet_result,
        )
