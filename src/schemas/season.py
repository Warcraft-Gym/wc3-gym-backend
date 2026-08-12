from typing import TYPE_CHECKING, Annotated

from src.schemas.base import APISchema, EmptyToNone, IsoDate, LenientDate, NumToStr
from src.schemas.map import Map

if TYPE_CHECKING:
    from src.schemas.user import User

DB_FIELDS = {
    'id', 'name', 'number_weeks', 'series_per_week', 'pick_ban',
    'start_date', 'end_date', 'discordRole',
}


class Season(APISchema):
    id: int | None = None
    name: Annotated[str | None, NumToStr] = None
    number_weeks: int | None = None
    series_per_week: int | None = None
    pick_ban: Annotated[str | None, NumToStr] = None
    start_date: Annotated[IsoDate | None, LenientDate] = None
    end_date: Annotated[IsoDate | None, LenientDate] = None
    maps: Annotated[list[Map] | None, EmptyToNone] = None
    discordRole: Annotated[str | None, NumToStr] = None
    user_signup: Annotated[list['User'] | None, EmptyToNone] = None

    def to_db_dict(self):
        return self.model_dump(include=DB_FIELDS)

    @classmethod
    def from_dbseason(cls, season):
        if not season:
            return None

        return cls(
            id=season.id,
            name=season.name,
            number_weeks=season.number_weeks,
            series_per_week=season.series_per_week,
            pick_ban=season.pick_ban,
            start_date=season.start_date,
            end_date=season.end_date,
            maps=[Map.from_dbmap(map_season.map) for map_season in (season.maps or []) if map_season and map_season.map],
            discordRole=season.discordRole,
        )

    @classmethod
    def from_dbseason_reduced(cls, season):
        if not season:
            return None

        return cls(
            id=season.id,
            name=season.name,
        )

    @staticmethod
    def schema():
        return {
            'type': 'object',
            'properties': {
                'name': {'type': 'string'},
                'number_weeks' : {'type': 'integer'},
                'series_per_week': {'type': 'integer'},
                'pick_ban' : {'type' : 'string', 'description': 'e.g. Ban_A|Ban_B|Ban_B|Ban_A|Pick_A|Pick_B'},
                'discordRole' : {'type': 'string'}
            },
            'required': ['name','number_weeks']
        }
