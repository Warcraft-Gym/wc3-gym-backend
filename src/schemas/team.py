from typing import Annotated, Any

from pydantic import BeforeValidator

from src.schemas.base import APISchema, NoneToList, NumToStr
from src.schemas.season_info import SeasonInfo
from src.schemas.user import User


def _season_lists(value: Any) -> Any:
    """Per-season lists: drop empty seasons and None entries (old to_dict behavior)."""
    if not value:
        return {}
    if not isinstance(value, dict):
        return value
    result = {}
    for season, items in value.items():
        if items:
            result[season] = [item for item in items if item is not None]
    return result


SeasonLists = BeforeValidator(_season_lists)


class TeamReduced(APISchema):
    id: int | None = None
    # name/long_name also receive numeric cells from the xlsx import.
    name: Annotated[str | None, NumToStr] = None
    long_name: Annotated[str | None, NumToStr] = None
    discord_role: Annotated[str | None, NumToStr] = None

    @classmethod
    def from_dbteam(cls, team):
        return cls(
            id=team.id,
            name=team.name,
            long_name=team.long_name,
            discord_role=team.discord_role,
        )


class Team(TeamReduced):
    player_by_season: Annotated[dict[int, list[User]], SeasonLists] = {}
    coaches_by_season: Annotated[dict[int, list[User]], SeasonLists] = {}
    seasons_info: Annotated[list[SeasonInfo], NoneToList] = []

    def to_db_dict(self):
        return self.model_dump(include={"name", "long_name", "discord_role"})

    @classmethod
    def from_dbteam(cls, team):
        if not team:
            return None

        u = {}
        coaches = {}
        seasons_info = (
            [
                s
                for s in (
                    SeasonInfo.from_dbseasoninfo(info) for info in team.season_info
                )
                if s
            ]
            if team.season_info
            else []
        )

        if team.user_seasons:
            for ut in team.user_seasons:
                if not u.get(ut.season_id):
                    u[ut.season_id] = []
                user = User.from_dbuser(ut.user)
                if user:
                    for gnl_stat in user.gnl_stats:
                        if gnl_stat.season_id == ut.season_id:
                            user.gnl_stats = [gnl_stat]
                            break
                    u.get(ut.season_id).append(user)

        # Load coaches from team_season entries
        if team.season_info:
            for season_info in team.season_info:
                season_id = season_info.season_id
                season_coaches = []

                # Add each coach if they exist
                if season_info.coach_1_id and season_info.coach_1:
                    coach = User.from_dbuser(season_info.coach_1)
                    if coach:
                        season_coaches.append(coach)

                if season_info.coach_2_id and season_info.coach_2:
                    coach = User.from_dbuser(season_info.coach_2)
                    if coach:
                        season_coaches.append(coach)

                if season_info.coach_3_id and season_info.coach_3:
                    coach = User.from_dbuser(season_info.coach_3)
                    if coach:
                        season_coaches.append(coach)

                if season_coaches:
                    coaches[season_id] = season_coaches

        return cls(
            id=team.id,
            name=team.name,
            long_name=team.long_name,
            discord_role=team.discord_role,
            player_by_season=u,
            coaches_by_season=coaches,
            seasons_info=seasons_info,
        )

    @staticmethod
    def schema():
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "long_name": {"type": "string"},
                "discord_role": {"type": "string"},
            },
            "required": ["name"],
        }
