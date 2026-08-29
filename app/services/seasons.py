import logging

from sqlalchemy import ColumnElement, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, noload, selectinload

from app.core.exceptions import BadRequestError, NotFoundError
from app.core.query import QueryElement, QueryUtil
from app.models.enums import Race
from app.models.ladder_achievement import default_rows
from app.models.map import Map
from app.models.relationships import DBMapSeason, DBUserSeasonSignup
from app.models.season import Season, SeasonCreate, SeasonPublic, SeasonUpdate
from app.models.team import Team
from app.models.team_season import DBTeamSeason
from app.models.user import User, UserListPublic
from app.services.base import BaseService
from app.services.users import UserService

logger = logging.getLogger(__name__)


class SeasonService(BaseService):
    def __init__(self, user_app_service: UserService) -> None:
        self.user_app_service = user_app_service

    def add(self, season: SeasonCreate) -> SeasonPublic:
        with self.get_session() as session:
            new_season = Season.add(session, season.model_dump())
            # A new season scores like the last one until an admin re-prices it
            session.add_all(default_rows(new_season.id))
            session.flush()
            return SeasonPublic.from_season(new_season)

    def update(self, season_id: int, season: SeasonUpdate) -> SeasonPublic:
        with self.get_session() as session:
            season = Season.update(
                session, season_id, **season.model_dump(exclude_unset=True)
            )
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
            if not season:
                raise NotFoundError("Season not found")
            return SeasonPublic.from_season(season)

    def get_all(self, limit: int | None = None, offset: int = 0) -> list[SeasonPublic]:
        with self.get_session() as session:
            result = []
            # Eager load related entities, disable nested loading except for maps
            statement = select(Season).options(
                # noload alone; a joined link table multiplies the rows
                noload(Season.user_teams),
                noload(Season.teams),
                selectinload(Season.maps).joinedload(DBMapSeason.map),
                noload(Season.signup_users),
            )
            if limit is not None or offset:
                # Offset paging is deterministic only with a fixed order
                statement = statement.order_by(Season.id).offset(offset)
                if limit is not None:
                    statement = statement.limit(limit)
            seasons = session.scalars(statement).unique().all()
            for season in seasons:
                result.append(SeasonPublic.from_season(season))
            return result

    def add_teams(self, season_id: int, team_ids: list[int]) -> SeasonPublic:
        with self.get_session() as session:
            season = session.get(Season, season_id)
            if not season:
                raise NotFoundError(f"Season not found by id: {season_id}")
            for team_id in team_ids:
                team = session.get(Team, team_id)
                if not team:
                    raise NotFoundError(f"Team not found by id: {team_id}")
                try:
                    # The primary key decides: a duplicate link is already there
                    with session.begin_nested():
                        session.add(DBTeamSeason(season=season, team=team))
                except IntegrityError:
                    logger.debug(f"Team {team_id} is already in season {season_id}")
            session.flush()
            return SeasonPublic.from_season(season)

    def search(
        self, query: QueryElement | None, limit: int | None = None, offset: int = 0
    ) -> list[SeasonPublic]:
        return self._where(
            QueryUtil.convert_query_to_db_filter(Season, query),
            limit=limit,
            offset=offset,
        )

    def _where(
        self,
        filter: ColumnElement[bool] | None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[SeasonPublic]:
        with self.get_session() as session:
            result = []
            # Eager load related entities, disable nested loading except for maps
            statement = (
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
            if limit is not None or offset:
                # Offset paging is deterministic only with a fixed order
                statement = statement.order_by(Season.id).offset(offset)
                if limit is not None:
                    statement = statement.limit(limit)
            seasons = (
                session.scalars(statement).unique().all() if filter is not None else []
            )
            if not seasons:
                logger.debug(f"No seasons found by searchcriteria: {filter}")
                return result
            for season in seasons:
                result.append(SeasonPublic.from_season(season))
            return result

    def remove_teams(self, season_id: int, team_ids: list[int]) -> SeasonPublic:
        with self.get_session() as session:
            season = session.get(Season, season_id)
            if not season:
                raise NotFoundError(f"Season not found by id: {season_id}")
            for team_id in team_ids:
                team = session.get(Team, team_id)
                if not team:
                    raise NotFoundError(f"Team not found by id: {team_id}")
                team_season = session.get(
                    DBTeamSeason, {"season_id": season_id, "team_id": team_id}
                )
                if not team_season:
                    raise BadRequestError(
                        f"Team not part of the season, team id: {team_id}, season id {season_id}"
                    )
                session.delete(team_season)
            session.flush()
            return SeasonPublic.from_season(season)

    def add_maps(self, season_id: int, map_ids: list[int]) -> SeasonPublic:
        with self.get_session() as session:
            season = session.get(Season, season_id)
            if not season:
                raise NotFoundError(f"Season not found by id: {season_id}")
            for map_id in map_ids:
                map = session.get(Map, map_id)
                if not map:
                    raise NotFoundError(f"Map not found by id: {map_id}")
                try:
                    # The primary key decides: a duplicate link is already there
                    with session.begin_nested():
                        session.add(DBMapSeason(season=season, map=map))
                except IntegrityError:
                    logger.debug(f"Map {map_id} is already in season {season_id}")
            session.flush()
            return SeasonPublic.from_season(season)

    def remove_maps(self, season_id: int, map_ids: list[int]) -> SeasonPublic:
        with self.get_session() as session:
            season = session.get(Season, season_id)
            if not season:
                raise NotFoundError(f"Season not found by id: {season_id}")
            for map_id in map_ids:
                map = session.get(Map, map_id)
                if not map:
                    raise NotFoundError(f"Map not found by id: {map_id}")
                map_season = session.get(
                    DBMapSeason, {"season_id": season_id, "map_id": map.id}
                )
                if not map_season:
                    raise BadRequestError(
                        f"Map not part of the season, map id: {map_id}, season id {season_id}"
                    )
                session.delete(map_season)
            session.flush()
            return SeasonPublic.from_season(season)

    def add_user_signup(
        self, season_id: int, user_ids: list[int], race: str | None = None
    ) -> SeasonPublic:
        """Sign these users up, all on the race the caller names, if any."""
        with self.get_session() as session:
            season = session.get(Season, season_id)
            if not season:
                raise NotFoundError(f"Season not found by id: {season_id}")
            signup_race = self._race(race)
            for user_id in user_ids:
                user = session.get(User, user_id)
                if not user:
                    raise NotFoundError(f"User not found by id: {user_id}")
                try:
                    # The primary key decides: a duplicate link is already there
                    with session.begin_nested():
                        session.add(
                            DBUserSeasonSignup(
                                season=season, user=user, race=signup_race
                            )
                        )
                except IntegrityError:
                    logger.debug(f"User {user_id} is already signed up to {season_id}")
            session.flush()
            return SeasonPublic.from_season(season)

    @staticmethod
    def _race(race: str | None) -> Race | None:
        """The race a signup names, read the way a person writes it."""
        if not race:
            return None
        try:
            return Race.from_text(race)
        except ValueError as error:
            raise BadRequestError(str(error)) from None

    def remove_user_signup(self, season_id: int, user_ids: list[int]) -> SeasonPublic:
        with self.get_session() as session:
            season = session.get(Season, season_id)
            if not season:
                raise NotFoundError(f"Season not found by id: {season_id}")
            for user_id in user_ids:
                user = session.get(User, user_id)
                if not user:
                    raise NotFoundError(f"User not found by id: {user_id}")
                user_season = session.get(
                    DBUserSeasonSignup, {"season_id": season_id, "user_id": user.id}
                )
                if not user_season:
                    raise BadRequestError(
                        f"User not signed up for the season, user id: {user_id}, season id {season_id}"
                    )
                session.delete(user_season)
            session.flush()
            return SeasonPublic.from_season(season)

    def get_signed_up_users(
        self, season_id: int, limit: int | None = None, offset: int = 0
    ) -> list[UserListPublic]:
        with self.get_session() as session:
            if session.scalar(select(Season.id).where(Season.id == season_id)) is None:
                raise NotFoundError("Season not found")

            # The signup row has no gnl_stats, so the link rows stay out
            statement = (
                select(DBUserSeasonSignup)
                .options(
                    joinedload(DBUserSeasonSignup.user)
                    .joinedload(User.w3c_stats)
                    .noload("*"),
                    joinedload(DBUserSeasonSignup.user).noload(User.team_seasons),
                )
                .where(DBUserSeasonSignup.season_id == season_id)
            )
            if limit is not None or offset:
                # Offset paging is deterministic only with a fixed order
                statement = statement.order_by(DBUserSeasonSignup.user_id).offset(
                    offset
                )
                if limit is not None:
                    statement = statement.limit(limit)

            result = []
            for signup in session.scalars(statement).unique().all():
                if signup.user:
                    user_public = UserListPublic.from_user(signup.user)
                    if user_public:
                        user_public.signup_race = signup.race
                        result.append(user_public)

            return result
