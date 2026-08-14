from app.models.user import UserPublic
from app.schemas.base import APISchema

DB_FIELDS = {
    "user_id",
    "player_name",
    "historical_rating",
    "historical_series_won",
    "historical_series_lost",
    "historical_games_won",
    "historical_games_lost",
    "historical_seasons_played",
    "rating",
    "series_won",
    "series_lost",
    "series_winrate",
    "games_won",
    "games_lost",
    "games_winrate",
    "seasons_played",
    "avg_series_per_season",
}

# The old to_dict() coerced these to float and mapped None/0 to 0.0.
_FLOAT_FIELDS = ("series_winrate", "games_winrate", "avg_series_per_season")


class PlayerCareerStats(APISchema):
    id: int | None = None
    user_id: int | None = None
    player_name: str | None = None
    user: UserPublic | None = None
    # Historical baseline
    historical_rating: int | None = None
    historical_series_won: int | None = None
    historical_series_lost: int | None = None
    historical_games_won: int | None = None
    historical_games_lost: int | None = None
    historical_seasons_played: int | None = None
    # Combined totals
    rating: int | None = None
    series_won: int | None = None
    series_lost: int | None = None
    series_winrate: float | None = None
    games_won: int | None = None
    games_lost: int | None = None
    games_winrate: float | None = None
    seasons_played: int | None = None
    avg_series_per_season: float | None = None

    def to_dict(self):
        result = super().to_dict()
        for key in _FLOAT_FIELDS:
            result[key] = result[key] if result[key] else 0.0
        return result

    def to_db_dict(self):
        """Convert DTO to dictionary for DB operations (excludes id and relationships)"""
        return self.model_dump(include=DB_FIELDS)

    @classmethod
    def from_db(cls, stats):
        if not stats:
            return None

        return cls(
            id=stats.id,
            user_id=stats.user_id,
            player_name=stats.player_name,
            user=UserPublic.from_user(stats.user) if stats.user else None,
            # Historical baseline
            historical_rating=stats.historical_rating,
            historical_series_won=stats.historical_series_won,
            historical_series_lost=stats.historical_series_lost,
            historical_games_won=stats.historical_games_won,
            historical_games_lost=stats.historical_games_lost,
            historical_seasons_played=stats.historical_seasons_played,
            # Combined totals
            rating=stats.rating,
            series_won=stats.series_won,
            series_lost=stats.series_lost,
            series_winrate=stats.series_winrate,
            games_won=stats.games_won,
            games_lost=stats.games_lost,
            games_winrate=stats.games_winrate,
            seasons_played=stats.seasons_played,
            avg_series_per_season=stats.avg_series_per_season,
        )
