from src.schemas.base import APISchema
from src.schemas.season import Season


class SeasonInfo(APISchema):
    season_id: int | None = None
    final_score: int | None = None
    points_available: int | None = None
    points_against: int | None = None
    season: Season | None = None

    def to_db_dict(self):
        return self.model_dump(
            include={'season_id', 'final_score', 'points_available', 'points_against'}
        )

    @classmethod
    def from_dbseasoninfo(cls, season_info):
        if not season_info:
            return None

        return cls(
            season_id=season_info.season_id,
            final_score=season_info.final_score,
            points_available=season_info.points_available,
            points_against=season_info.points_against,
            season=Season.from_dbseason(season_info.season) if season_info.season else None,
        )

    @staticmethod
    def schema():
        from src.database.model.DBSeason import DBSeason
        return {
            'type': 'object',
            'properties': {
                'season_id': {'type': 'integer'},
                'final_score': {'type': 'integer'},
                'points_available': {'type': 'integer'},
                'points_against': {'type': 'integer'},
                'season': {'type': DBSeason},
            }
        }
