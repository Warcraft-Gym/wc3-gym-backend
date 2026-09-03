import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import joinedload, noload, selectinload
from sqlmodel import col

from app.core.db import Session, rel
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.query import QueryElement, QueryUtil
from app.models.enums import Race
from app.models.ladder_achievement import default_rows
from app.models.map import LadderMapRow, Map
from app.models.relationships import (
    DBMapSeason,
    DBSeasonWeekMap,
    DBUserSeasonSignup,
)
from app.models.season import (
    Season,
    SeasonCreate,
    SeasonPublic,
    SeasonSignupUpdate,
    SeasonUpdate,
    tier_of,
)
from app.models.team import Team
from app.models.team_season import DBTeamSeason
from app.models.user import User, UserListPublic
from app.services import ladder_maps
from app.services.ladder import mmr_on
from app.services.maps import MapService
from app.services.series_veto import check_order
from app.services.users import UserService

logger = logging.getLogger(__name__)


# A season answers its map pool and its week maps and nothing else; noload
# alone, because a joined link table multiplies the rows.
_SEASON_OPTIONS = (
    noload(rel(Season.user_teams)),
    noload(rel(Season.teams)),
    selectinload(rel(Season.maps)).joinedload(rel(DBMapSeason.map)),
    selectinload(rel(Season.week_maps)),
    noload(rel(Season.signup_users)),
)


def _public(session: OrmSession, season: Season) -> SeasonPublic:
    """The full season with its phase; the phase is one aggregate over its series."""
    public = SeasonPublic.from_season(season)
    public.phase, public.unscored_series = season.progress(session)
    return public


class SeasonService:
    def __init__(
        self, user_app_service: UserService, map_app_service: MapService
    ) -> None:
        self.user_app_service = user_app_service
        self.map_app_service = map_app_service

    def add(self, season: SeasonCreate) -> SeasonPublic:
        with Session.begin() as session:
            new_season = Season.add(session, season.model_dump())
            # A new season scores like the last one until an admin re-prices it
            session.add_all(default_rows(new_season.id))
            session.flush()
            return _public(session, new_season)

    def update(self, season_id: int, season: SeasonUpdate) -> SeasonPublic:
        with Session.begin() as session:
            row = Season.update(
                session, season_id, **season.model_dump(exclude_unset=True)
            )
            if not row:
                raise NotFoundError("Season not found")
            if season.model_fields_set & {"pick_ban", "map_rules"}:
                check_order(row)
            return _public(session, row)

    def delete(self, season_id: int) -> None:
        with Session.begin() as session:
            Season.delete(session, season_id)

    def get(self, season_id: int) -> SeasonPublic:
        with Session.begin() as session:
            season = (
                session.scalars(
                    select(Season)
                    .options(*_SEASON_OPTIONS)
                    .where(col(Season.id) == season_id)
                )
                .unique()
                .first()
            )
            if not season:
                raise NotFoundError("Season not found")
            return _public(session, season)

    def get_all(self, limit: int | None = None, offset: int = 0) -> list[SeasonPublic]:
        with Session.begin() as session:
            # Offset paging is deterministic only with a fixed order
            statement = (
                select(Season)
                .options(*_SEASON_OPTIONS)
                .order_by(col(Season.id))
                .offset(offset)
                .limit(limit)
            )
            seasons = session.scalars(statement).unique().all()
            return [_public(session, season) for season in seasons]

    def add_teams(self, season_id: int, team_ids: list[int]) -> SeasonPublic:
        with Session.begin() as session:
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
            return _public(session, season)

    def search(
        self, query: QueryElement | None, limit: int | None = None, offset: int = 0
    ) -> list[SeasonPublic]:
        filter = QueryUtil.convert_query_to_db_filter(Season, query)
        if filter is None:
            return []
        with Session.begin() as session:
            # Offset paging is deterministic only with a fixed order
            statement = (
                select(Season)
                .options(*_SEASON_OPTIONS)
                .where(filter)
                .order_by(col(Season.id))
                .offset(offset)
                .limit(limit)
            )
            seasons = session.scalars(statement).unique().all()
            return [_public(session, season) for season in seasons]

    def remove_teams(self, season_id: int, team_ids: list[int]) -> SeasonPublic:
        with Session.begin() as session:
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
            return _public(session, season)

    def add_maps(self, season_id: int, map_ids: list[int]) -> SeasonPublic:
        with Session.begin() as session:
            season = session.get(Season, season_id)
            if not season:
                raise NotFoundError(f"Season not found by id: {season_id}")
            # A new map joins the pool behind the ones already in it
            position = max((link.position for link in season.maps), default=-1) + 1
            for map_id in map_ids:
                map = session.get(Map, map_id)
                if not map:
                    raise NotFoundError(f"Map not found by id: {map_id}")
                try:
                    # The primary key decides: a duplicate link is already there
                    with session.begin_nested():
                        session.add(
                            DBMapSeason(season=season, map=map, position=position)
                        )
                    position += 1
                except IntegrityError:
                    logger.debug(f"Map {map_id} is already in season {season_id}")
            session.flush()
            return _public(session, season)

    def ladder_import_preview(self, season_id: int) -> list[LadderMapRow]:
        """Every 1v1 ladder map, and whether the season already plays it."""
        with Session.begin() as session:
            season = session.get(Season, season_id)
            if not season:
                raise NotFoundError(f"Season not found by id: {season_id}")
            pool = {
                ladder_maps.folded_base(link.map.name)
                for link in season.maps
                if link.map and link.map.name
            }
        rows = self.map_app_service.ladder_import_preview()
        for row in rows:
            if ladder_maps.folded_base(row.w3c_name) in pool:
                row.status = "in_pool"
        return rows

    def import_ladder_maps(self, season_id: int, names: list[str]) -> SeasonPublic:
        """Add these ladder maps to the pool; the map service creates, renames and pictures them."""
        with Session.begin() as session:
            if not session.get(Season, season_id):
                raise NotFoundError(f"Season not found by id: {season_id}")
        return self.add_maps(season_id, self.map_app_service.import_ladder_maps(names))

    def set_map_order(self, season_id: int, map_ids: list[int]) -> SeasonPublic:
        """Reorder the whole pool. The ids given are exactly the ids in it."""
        with Session.begin() as session:
            season = session.get(Season, season_id)
            if not season:
                raise NotFoundError(f"Season not found by id: {season_id}")
            pool = {link.map_id: link for link in season.maps}
            if sorted(map_ids) != sorted(pool):
                raise BadRequestError(
                    f"The order must name every map of the pool once, season id {season_id}"
                )
            for position, map_id in enumerate(map_ids):
                pool[map_id].position = position
            session.flush()
            # The loaded collection keeps its old order until it is read again
            session.expire(season, ["maps"])
            return _public(session, season)

    def set_week_map(
        self, season_id: int, playday: int, map_id: int | None
    ) -> SeasonPublic:
        """Name the game 1 map of one playday, or clear it with a null map."""
        with Session.begin() as session:
            season = session.get(Season, season_id)
            if not season:
                raise NotFoundError(f"Season not found by id: {season_id}")
            if not 1 <= playday <= season.number_weeks:
                raise BadRequestError(
                    f"playday must be between 1 and {season.number_weeks}"
                )
            if map_id is None:
                row = session.get(DBSeasonWeekMap, (season_id, playday))
                if row:
                    session.delete(row)
            elif map_id not in {link.map_id for link in season.maps}:
                raise BadRequestError(
                    f"Map not part of the season, map id: {map_id}, season id {season_id}"
                )
            else:
                session.merge(
                    DBSeasonWeekMap(season_id=season_id, playday=playday, map_id=map_id)
                )
            session.flush()
            session.expire(season, ["week_maps"])
            return _public(session, season)

    def remove_maps(self, season_id: int, map_ids: list[int]) -> SeasonPublic:
        with Session.begin() as session:
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
            # A week map has to come from the pool, so it leaves with its map.
            for week_map in list(season.week_maps):
                if week_map.map_id in map_ids:
                    session.delete(week_map)
            session.flush()
            session.refresh(season)
            # A smaller pool may no longer carry the order
            check_order(season)
            return _public(session, season)

    def add_user_signup(
        self, season_id: int, user_ids: list[int], race: str | None = None
    ) -> SeasonPublic:
        """Sign these users up, all on the race the caller names, if any."""
        with Session.begin() as session:
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
            return _public(session, season)

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
        with Session.begin() as session:
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
            return _public(session, season)

    def update_signup(
        self, season_id: int, user_id: int, data: SeasonSignupUpdate
    ) -> SeasonPublic:
        with Session.begin() as session:
            signup = session.get(
                DBUserSeasonSignup, {"season_id": season_id, "user_id": user_id}
            )
            if not signup:
                raise NotFoundError(
                    f"User not signed up for the season, user id: {user_id}, season id {season_id}"
                )
            signup.sqlmodel_update(data.model_dump())
            session.flush()
            return _public(session, signup.season)

    def get_signed_up_users(
        self, season_id: int, limit: int | None = None, offset: int = 0
    ) -> list[UserListPublic]:
        with Session.begin() as session:
            season = session.get(Season, season_id)
            if season is None:
                raise NotFoundError("Season not found")

            # The signup row has no gnl_stats, so the link rows stay out
            statement = (
                select(DBUserSeasonSignup)
                .options(
                    joinedload(rel(DBUserSeasonSignup.user))
                    .joinedload(rel(User.w3c_stats))
                    .noload("*"),
                    joinedload(rel(DBUserSeasonSignup.user)).noload(
                        rel(User.team_seasons)
                    ),
                )
                .where(col(DBUserSeasonSignup.season_id) == season_id)
                # Offset paging is deterministic only with a fixed order
                .order_by(col(DBUserSeasonSignup.user_id))
                .offset(offset)
                .limit(limit)
            )

            signups = session.scalars(statement).unique().all()
            cuts, applied = season.fantasy_tier_cuts, season.fantasy_tiers_applied_at
            # An unpinned tier is the band the player's MMR on the Apply date falls in
            mmrs = (
                mmr_on(session, [signup.user_id for signup in signups], applied)
                if cuts and applied
                else {}
            )
            result = []
            for signup in signups:
                if signup.user:
                    user_public = UserListPublic.from_user(signup.user)
                    if user_public:
                        user_public.signup_race = (
                            signup.race.value if signup.race else None
                        )
                        # A season allocated before it had an Apply date stored every
                        # tier, so those read as the allocation, not as pins
                        user_public.fantasy_tier_pinned = (
                            signup.fantasy_tier is not None and applied is not None
                        )
                        user_public.mmr_override = signup.mmr_override
                        mmr = mmrs.get((signup.user_id, signup.race))
                        user_public.fantasy_tier = signup.fantasy_tier or (
                            tier_of(mmr, cuts) if mmr is not None and cuts else None
                        )
                        result.append(user_public)

            return result
