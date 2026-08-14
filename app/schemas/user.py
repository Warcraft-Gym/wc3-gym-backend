from typing import Annotated

from app.models.enums import Race
from app.schemas.base import APISchema, NoneToList, NumToStr
from app.schemas.season import Season
from app.schemas.user_team_season_stats import UserTeamSeasonStats
from app.schemas.w3c_stats import W3CStats

DB_FIELDS = {
    "id",
    "name",
    "battleTag",
    "discordTag",
    "discordId",
    "race",
    "mmr",
    "country",
    "fantasy_tier",
}


class User(APISchema):
    id: int | None = None
    # These fields receive raw numeric cells from the xlsx import, and
    # discordId also receives numeric snowflakes from JSON bodies.
    name: Annotated[str | None, NumToStr] = None
    battleTag: Annotated[str | None, NumToStr] = None
    discordTag: Annotated[str | None, NumToStr] = None
    discordId: Annotated[str | None, NumToStr] = None
    race: Race | str | None = None
    mmr: int | None = None
    country: Annotated[str | None, NumToStr] = None
    w3c_stats: Annotated[list[W3CStats], NoneToList] = []
    gnl_stats: Annotated[list[UserTeamSeasonStats], NoneToList] = []
    fantasy_tier: int | None = None
    signup_seasons: Annotated[list[Season], NoneToList] = []

    def to_db_dict(self):
        return self.model_dump(include=DB_FIELDS)

    @classmethod
    def from_dbuser(cls, user):
        if not user:
            return None

        return cls(
            id=user.id,
            name=user.name,
            battleTag=user.battleTag,
            discordTag=user.discordTag,
            discordId=user.discordId,
            race=user.race,
            mmr=user.mmr,
            country=user.country,
            w3c_stats=[
                W3CStats.from_dbw3cstats(stat) for stat in (user.w3c_stats or [])
            ],
            gnl_stats=[
                UserTeamSeasonStats.from_db_user_team_season(stat)
                for stat in (user.team_seasons or [])
            ],
            fantasy_tier=user.fantasy_tier,
            signup_seasons=[
                Season.from_dbseason_reduced(signup.season)
                for signup in (user.signup_seasons or [])
            ],
        )
