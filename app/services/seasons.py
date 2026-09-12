import logging
from collections.abc import Sequence
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import joinedload, noload, selectinload
from sqlmodel import col

from app.core.db import Session, rel
from app.core.exceptions import ApiError, BadRequestError, NotFoundError
from app.core.query import QueryElement, QueryUtil
from app.models.base import ident
from app.models.enums import Race
from app.models.ladder_achievement import (
    LadderAchievement,
    SeasonAchievementPublic,
    SeasonAchievementWrite,
    default_rows,
)
from app.models.map import LadderMapRow, Map
from app.models.relationships import (
    DBMapSeason,
    DBSeasonRound,
    DBUserSeasonSignup,
    SeasonRoundWrite,
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
    selectinload(rel(Season.rounds)),
    noload(rel(Season.signup_users)),
)


def _achievement_set(
    session: OrmSession, season_id: int
) -> list[SeasonAchievementPublic]:
    from app.core.achievements import BY_ID

    order = {rule_id: n for n, rule_id in enumerate(BY_ID)}
    rows = session.scalars(
        select(LadderAchievement).where(col(LadderAchievement.season_id) == season_id)
    ).all()
    return [
        SeasonAchievementPublic.of(row.rule_id, row.points, row.params)
        for row in sorted(rows, key=lambda row: order.get(row.rule_id, len(order)))
        if row.rule_id in BY_ID
    ]


def _wanted(season: SeasonCreate | SeasonUpdate) -> int | None:
    """The round count the caller asked for."""
    return season.round_count


def fill_rounds(session: OrmSession, season: Season, wanted: int) -> None:
    """One round per playday, `wanted` of them. A missing round is added a week
    after the one before it; a round past the last playday is dropped; a set
    date stays. The rows are the round count, so nothing stores it."""
    rounds = {row.playday: row for row in season.rounds}
    for playday in range(1, wanted + 1):
        row = rounds.get(playday) or DBSeasonRound(
            season_id=ident(season), playday=playday
        )
        # ponytail: weekly rounds, the GNL cadence; a stage cadence when cups need it
        if row.start_date is None and season.start_date:
            row.start_date = season.start_date + timedelta(weeks=playday - 1)
            row.end_date = row.start_date + timedelta(days=6)
        session.add(row)
    for playday, row in rounds.items():
        if playday > wanted:
            session.delete(row)
    session.flush()
    session.expire(season, ["rounds", "round_count"])


def resolved_tiers(
    session: OrmSession, season: Season, signups: Sequence[DBUserSeasonSignup]
) -> dict[int, int | None]:
    """Each signup's fantasy tier: the pin, else the band its MMR on the Apply date falls in."""
    cuts, applied = season.fantasy_tier_cuts, season.fantasy_tiers_applied_at
    mmrs = (
        mmr_on(session, [signup.user_id for signup in signups], applied)
        if cuts and applied
        else {}
    )
    tiers = {}
    for signup in signups:
        mmr = mmrs.get((signup.user_id, signup.race))
        tiers[signup.user_id] = signup.fantasy_tier or (
            tier_of(mmr, cuts) if mmr is not None and cuts else None
        )
    return tiers


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
            new_season = Season.add(session, season.model_dump(exclude={"round_count"}))
            # A new season scores like the last one until an admin re-prices it
            session.add_all(default_rows(new_season.id))
            session.flush()
            fill_rounds(session, new_season, _wanted(season) or 0)
            return _public(session, new_season)

    def update(self, season_id: int, season: SeasonUpdate) -> SeasonPublic:
        with Session.begin() as session:
            row = Season.update(
                session,
                season_id,
                **season.model_dump(exclude_unset=True, exclude={"round_count"}),
            )
            if not row:
                raise NotFoundError("Season not found")
            if season.model_fields_set & {"pick_ban", "map_rules"}:
                check_order(row)
            if season.model_fields_set & {"round_count", "start_date"}:
                wanted = _wanted(season)
                fill_rounds(session, row, row.round_count if wanted is None else wanted)
            return _public(session, row)

    def delete(self, season_id: int) -> None:
        with Session.begin() as session:
            Season.delete(session, season_id)

    def achievements(self, season_id: int) -> list[SeasonAchievementPublic]:
        """The rules this season pays, in catalogue order."""
        with Session.begin() as session:
            if session.get(Season, season_id) is None:
                raise NotFoundError("Season not found")
            return _achievement_set(session, season_id)

    def set_achievements(
        self, season_id: int, rows: list[SeasonAchievementWrite]
    ) -> list[SeasonAchievementPublic]:
        """Replace the season's set. A row stores only the numbers that differ
        from the rule's defaults, so an untouched row follows the code."""
        from app.core.achievements import BY_ID

        if len({row.rule_id for row in rows}) < len(rows):
            raise BadRequestError("A rule is listed twice")
        with Session.begin() as session:
            if session.get(Season, season_id) is None:
                raise NotFoundError("Season not found")
            session.execute(
                delete(LadderAchievement).where(
                    col(LadderAchievement.season_id) == season_id
                )
            )
            session.add_all(
                LadderAchievement(
                    season_id=season_id,
                    rule_id=row.rule_id,
                    points=row.points,
                    params={
                        key: value
                        for key, value in row.params.items()
                        if value != BY_ID[row.rule_id].params[key]
                    },
                )
                for row in rows
            )
            session.flush()
            return _achievement_set(session, season_id)

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

    def refuse_unless_open(self, season_id: int) -> None:
        """A fantasy team is drafted before the season commences; the admin routes stay open."""
        phase = self.get(season_id).phase
        if phase in ("commenced", "overdue"):
            raise ApiError(
                403,
                {"error": "season_commenced", "message": "The season has commenced"},
            )
        if phase == "complete":
            raise ApiError(
                403,
                {"error": "season_ended", "message": "The season has ended"},
            )

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

    def set_round(self, season_id: int, data: SeasonRoundWrite) -> SeasonPublic:
        """Set the dates and the game 1 map of one round.

        A field left out of the write keeps its value; a null clears it.
        """
        with Session.begin() as session:
            season = session.get(Season, season_id)
            if not season:
                raise NotFoundError(f"Season not found by id: {season_id}")
            if not 1 <= data.playday <= season.round_count:
                raise BadRequestError(
                    f"playday must be between 1 and {season.round_count}"
                )
            fields = data.model_dump(exclude_unset=True, exclude={"playday"})
            map_id = fields.get("map_id")
            if map_id is not None and map_id not in {
                link.map_id for link in season.maps
            }:
                raise BadRequestError(
                    f"Map not part of the season, map id: {map_id}, season id {season_id}"
                )
            row = session.get(
                DBSeasonRound, (season_id, data.playday)
            ) or DBSeasonRound(season_id=season_id, playday=data.playday)
            row.sqlmodel_update(fields)
            if row.end_date and row.start_date and row.end_date < row.start_date:
                raise BadRequestError("end_date must not be before start_date")
            session.add(row)
            session.flush()
            session.expire(season, ["rounds", "round_count"])
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
            # A round's map has to come from the pool, so it leaves with its map.
            for round_ in season.rounds:
                if round_.map_id in map_ids:
                    round_.map_id = None
            session.flush()
            session.refresh(season)
            # A smaller pool may no longer carry the order
            check_order(season)
            return _public(session, season)

    def add_user_signup(
        self, season_id: int, user_ids: list[int], race: str
    ) -> SeasonPublic:
        """Sign these users up, all on the race the caller names."""
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
    def _race(race: str | None) -> Race:
        """The race a signup names, read the way a person writes it."""
        if not race:
            raise BadRequestError("A signup needs a race")
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
            fields = data.model_dump(exclude_unset=True)
            if "race" in fields:
                fields["race"] = self._race(fields["race"])
                phase, _ = signup.season.progress(session)
                if phase != "open" and fields["race"] != signup.race:
                    raise BadRequestError(
                        "A season that has started keeps its signup races. "
                        "Record the race played on the series instead."
                    )
            signup.sqlmodel_update(fields)
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
            applied = season.fantasy_tiers_applied_at
            # An unpinned tier is the band the player's MMR on the Apply date falls in
            tiers = resolved_tiers(session, season, signups)
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
                        user_public.draft_position = signup.draft_position
                        user_public.draft_excluded = signup.draft_excluded
                        user_public.fantasy_tier = tiers.get(signup.user_id)
                        result.append(user_public)

            return result
