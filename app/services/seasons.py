import logging

from sqlalchemy import ColumnElement, select
from sqlalchemy.orm import joinedload, noload, selectinload

from app.core.exceptions import NotFoundError
from app.core.query import QueryElement, QueryUtil
from app.models.map import Map
from app.models.relationships import DBMapSeason, DBUserSeasonSignup
from app.models.season import Season, SeasonCreate, SeasonPublic, SeasonUpdate
from app.models.team import Team
from app.models.team_season import DBTeamSeason
from app.models.user import User, UserPublic
from app.services.base import BaseService

logger = logging.getLogger(__name__)


class SeasonService(BaseService):
    def add(self, season: SeasonCreate) -> SeasonPublic:
        with self.get_session() as session:
            new_season = Season.add(session, season.model_dump())
            return SeasonPublic.from_season(new_season)

    def update(self, season_id: int, season: SeasonUpdate) -> SeasonPublic:
        with self.get_session() as session:
            season = Season.update(
                session, season_id, **season.model_dump(exclude_unset=True)
            )
            # Example usage
            if not season:
                raise NotFoundError("Season not found")
            return SeasonPublic.from_season(season)

    def delete(self, season_id: int) -> None:
        with self.get_session() as session:
            Season.delete(session, season_id)

    def get(self, season_id: int) -> SeasonPublic:
        with self.get_session() as session:
            # Eager load related entities, disable nested loading except for maps
            season = (
                session.scalars(
                    select(Season)
                    .options(
                        # noload alone; a joined link table multiplies the rows
                        noload(Season.user_teams),
                        noload(Season.teams),
                        selectinload(Season.maps).joinedload(DBMapSeason.map),
                        noload(Season.signup_users),
                    )
                    .where(Season.id == season_id)
                )
                .unique()
                .first()
            )
            # Example usage
            if not season:
                raise NotFoundError("Season not found")
            return SeasonPublic.from_season(season)

    def getAll(self) -> list[SeasonPublic]:
        with self.get_session() as session:
            result = []
            # Eager load related entities, disable nested loading except for maps
            seasons = (
                session.scalars(
                    select(Season).options(
                        # noload alone; a joined link table multiplies the rows
                        noload(Season.user_teams),
                        noload(Season.teams),
                        selectinload(Season.maps).joinedload(DBMapSeason.map),
                        noload(Season.signup_users),
                    )
                )
                .unique()
                .all()
            )
            for season in seasons:
                result.append(SeasonPublic.from_season(season))
            return result

    def addTeams(self, season_id: int, team_ids: list[int]) -> SeasonPublic:
        with self.get_session() as session:
            season = session.get(Season, season_id)
            if not season:
                raise Exception(f"Season not found by id: {season_id}")
            for team_id in team_ids:
                team = session.get(Team, team_id)
                if not team:
                    raise Exception(f"Team not found by id: {team_id}")
                already_exists = (
                    session.get(
                        DBTeamSeason, {"season_id": season_id, "team_id": team.id}
                    )
                    is not None
                )
                if not already_exists:
                    session.add(DBTeamSeason(season=season, team=team))
            session.flush()
            return SeasonPublic.from_season(season)

    def search(self, query: QueryElement | None) -> list[SeasonPublic]:
        return self._where(QueryUtil.convertQueryToDBFilter(Season, query))

    def find_by_name(self, name: str) -> list[SeasonPublic]:
        return self._where(Season.name == name)

    def _where(self, filter: ColumnElement[bool] | None) -> list[SeasonPublic]:
        with self.get_session() as session:
            result = []
            # Eager load related entities, disable nested loading except for maps
            seasons = (
                session.scalars(
                    select(Season)
                    .options(
                        # noload alone; a joined link table multiplies the rows
                        noload(Season.user_teams),
                        noload(Season.teams),
                        selectinload(Season.maps).joinedload(DBMapSeason.map),
                        noload(Season.signup_users),
                    )
                    .where(filter)
                )
                .unique()
                .all()
                if filter is not None
                else []
            )
            if not seasons:
                logger.debug(f"No seasons found by searchcriteria: {filter}")
                return result
            for season in seasons:
                result.append(SeasonPublic.from_season(season))
            return result

    def removeTeams(self, season_id: int, team_ids: list[int]) -> SeasonPublic:
        with self.get_session() as session:
            season = session.get(Season, season_id)
            if not season:
                raise Exception(f"Season not found by id: {season_id}")
            for team_id in team_ids:
                team = session.get(Team, team_id)
                if not team:
                    raise Exception(f"Team not found by id: {team_id}")
                team_season = session.get(
                    DBTeamSeason, {"season_id": season_id, "team_id": team_id}
                )
                if not team_season:
                    raise Exception(
                        f"Team not part of the season, team id: {team_id}, season id {season_id}"
                    )
                session.delete(team_season)
            session.flush()
            return SeasonPublic.from_season(season)

    def addMaps(self, season_id: int, map_ids: list[int]) -> SeasonPublic:
        with self.get_session() as session:
            season = session.get(Season, season_id)
            if not season:
                raise Exception(f"Season not found by id: {season_id}")
            for map_id in map_ids:
                map = session.get(Map, map_id)
                if not map:
                    raise Exception(f"Map not found by id: {map_id}")
                already_exists = (
                    session.get(DBMapSeason, {"season_id": season_id, "map_id": map.id})
                    is not None
                )
                if not already_exists:
                    session.add(DBMapSeason(season=season, map=map))
            session.flush()
            return SeasonPublic.from_season(season)

    def removeMaps(self, season_id: int, map_ids: list[int]) -> SeasonPublic:
        with self.get_session() as session:
            season = session.get(Season, season_id)
            if not season:
                raise Exception(f"Season not found by id: {season_id}")
            for map_id in map_ids:
                map = session.get(Map, map_id)
                if not map:
                    raise Exception(f"Map not found by id: {map_id}")
                map_season = session.get(
                    DBMapSeason, {"season_id": season_id, "map_id": map.id}
                )
                if not map_season:
                    raise Exception(
                        f"Map not part of the season, map id: {map_id}, season id {season_id}"
                    )
                session.delete(map_season)
            session.flush()
            return SeasonPublic.from_season(season)

    def addUserSignup(self, season_id: int, user_ids: list[int]) -> SeasonPublic:
        with self.get_session() as session:
            season = session.get(Season, season_id)
            if not season:
                raise Exception(f"Season not found by id: {season_id}")
            for user_id in user_ids:
                user = session.get(User, user_id)
                if not user:
                    raise Exception(f"User not found by id: {user_id}")
                already_exists = (
                    session.get(
                        DBUserSeasonSignup, {"season_id": season_id, "user_id": user.id}
                    )
                    is not None
                )
                if not already_exists:
                    session.add(DBUserSeasonSignup(season=season, user=user))
            session.flush()
            return SeasonPublic.from_season(season)

    def removeUserSignup(self, season_id: int, user_ids: list[int]) -> SeasonPublic:
        with self.get_session() as session:
            season = session.get(Season, season_id)
            if not season:
                raise Exception(f"Season not found by id: {season_id}")
            for user_id in user_ids:
                user = session.get(User, user_id)
                if not user:
                    raise Exception(f"User not found by id: {user_id}")
                user_season = session.get(
                    DBUserSeasonSignup, {"season_id": season_id, "user_id": user.id}
                )
                if not user_season:
                    raise Exception(
                        f"User not signed up for the season, user id: {user_id}, season id {season_id}"
                    )
                session.delete(user_season)
            session.flush()
            return SeasonPublic.from_season(season)

    def getSignedUpUsers(self, season_id: int) -> list[UserPublic]:
        with self.get_session() as session:
            # Eager load signup users with their user data and w3c_stats
            season = (
                session.scalars(
                    select(Season)
                    .options(
                        joinedload(Season.signup_users)
                        .joinedload(DBUserSeasonSignup.user)
                        .joinedload(User.w3c_stats)
                        .noload("*"),
                        joinedload(Season.signup_users)
                        .joinedload(DBUserSeasonSignup.user)
                        .joinedload(User.team_seasons)
                        .noload("*"),
                    )
                    .where(Season.id == season_id)
                )
                .unique()
                .first()
            )

            if not season:
                raise NotFoundError("Season not found")

            result = []
            if season.signup_users:
                for signup in season.signup_users:
                    if signup.user:
                        user_public = UserPublic.from_user(signup.user)
                        if user_public:
                            result.append(user_public)

            return result

    def create_season(self, season: SeasonCreate) -> SeasonPublic:
        return self.add(season)

    def update_season(self, season_id: int, season: SeasonUpdate) -> SeasonPublic:
        return self.update(season_id, season)

    def delete_season(self, season_id: int) -> None:
        self.delete(season_id)

    def get_season(self, season_id: int) -> SeasonPublic:
        season_data = self.get(season_id)
        if not season_data:
            raise NotFoundError(f"Season not found by Id: {season_id}")
        return season_data
