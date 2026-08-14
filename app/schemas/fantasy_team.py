from typing import Annotated

from pydantic import field_serializer

from app.models.enums import Race
from app.schemas.base import APISchema, DropNoneItems, NumToStr
from app.schemas.season import Season
from app.schemas.team import Team
from app.schemas.user import User

DB_FIELDS = {
    "name",
    "season_id",
    "captain_id",
    "drafted_team_id",
    "drafted_race",
    "player_points",
    "bench_points",
    "team_points",
    "race_points",
    "bet_points",
    "total_points",
}


class FantasyTeam(APISchema):
    id: int | None = None
    name: Annotated[str | None, NumToStr] = None
    season_id: int | None = None
    season: Season | None = None
    captain_id: int | None = None
    captain: User | None = None
    drafted_team_id: int | None = None
    drafted_team: Team | None = None
    drafted_race: Race | str | None = None
    # The attribute keeps the list it was given (the import endpoint iterates
    # it), while the JSON output shows null for an empty list - exactly like
    # the old DTO. So the empty-to-None step lives in the serializer, not in
    # a validator.
    drafted_players: Annotated[list[User] | None, DropNoneItems] = None
    player_points: int | None = None
    bench_points: int | None = None
    team_points: int | None = None
    race_points: int | None = None
    bet_points: int | None = None
    total_points: int | None = None

    @field_serializer("drafted_players", when_used="json")
    def _drafted_players_json(self, value):
        return [user.to_dict() for user in value] if value else None

    def to_db_dict(self):
        return self.model_dump(include=DB_FIELDS)

    @classmethod
    def from_dbfantasyteam(cls, fteam):
        if not fteam:
            return None

        drafted_players = []
        if fteam.drafted_players:
            for dp in fteam.drafted_players:
                user = User.from_dbuser(dp.users)
                if user:
                    drafted_players.append(user)

        return cls(
            id=fteam.id,
            name=fteam.name,
            season_id=fteam.season_id,
            season=Season.from_dbseason(fteam.season) if fteam.season else None,
            captain_id=fteam.captain_id,
            captain=User.from_dbuser(fteam.captain) if fteam.captain else None,
            drafted_team_id=fteam.drafted_team_id,
            drafted_team=Team.from_dbteam(fteam.drafted_team)
            if fteam.drafted_team
            else None,
            drafted_race=fteam.drafted_race,
            drafted_players=drafted_players,
            player_points=fteam.player_points,
            bench_points=fteam.bench_points,
            team_points=fteam.team_points,
            race_points=fteam.race_points,
            bet_points=fteam.bet_points,
            total_points=fteam.total_points,
        )

    @staticmethod
    def schema():
        return {
            "type": "object",
            "properties": {
                "season_id": {"type": "integer"},
                "captain_id": {"type": "integer"},
                "drafted_team_id": {"type": "integer"},
                "drafted_race": {"type": "integer"},
                "player_points": {"type": "integer"},
                "bench_points": {"type": "integer"},
                "team_points": {"type": "integer"},
                "race_points": {"type": "integer"},
                "bet_points": {"type": "integer"},
                "total_points": {"type": "integer"},
            },
            "required": ["season_id", "captain_id", "drafted_team_id", "drafted_race"],
        }
