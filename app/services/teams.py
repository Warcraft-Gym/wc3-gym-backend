import logging
from typing import Any

from sqlalchemy import select, true
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import joinedload, noload, selectinload
from sqlmodel import col

from app.core.db import Session, rel
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.query import QueryElement, QueryUtil
from app.models.base import ident
from app.models.enums import EntrantKind, LeagueKind
from app.models.league import League
from app.models.relationships import DBTeamSeasonCaptain
from app.models.season import Season, progress_by_seasons
from app.models.team import Team, TeamCreate, TeamPublic, TeamUpdate
from app.models.team_season import DBTeamSeason
from app.models.user import User, UserPublic
from app.models.user_team_season import DBUserTeamSeason
from app.services import blob, derived, discord_roles
from app.services.users import UserService

logger = logging.getLogger(__name__)


def _league(session: OrmSession, league_id: int) -> League:
    league = session.get(League, league_id)
    if not league:
        raise NotFoundError(f"League not found by id: {league_id}")
    return league


def _team(session: OrmSession, team_id: int, league_id: int | None = None) -> Team:
    team = session.get(Team, team_id)
    if not team or (league_id is not None and team.league_id != league_id):
        raise NotFoundError("Team not found")
    return team


def _event_team(
    session: OrmSession, team_id: int, event_id: int
) -> tuple[Team, Season]:
    """A team entered in an event of the same league."""
    event = session.get(Season, event_id)
    if not event:
        raise NotFoundError(f"Event not found by id: {event_id}")
    team = _team(session, team_id)
    if (
        team.league_id != event.league_id
        or session.get(DBTeamSeason, {"team_id": team_id, "season_id": event_id})
        is None
    ):
        raise NotFoundError("Team not found in event")
    return team, event


def _fill(session: OrmSession, teams: list[TeamPublic]) -> None:
    """The standings of every team, the name and league of every season it
    played, and the signup race and the season record of every player."""
    derived.fill_standings(session, teams)
    derived.fill_season_labels(session, teams)
    roster = [
        (player, season_id)
        for team in teams
        for season_id, players in team.player_by_season.items()
        for player in players
    ]
    derived.fill_user_signup_races(session, roster)
    derived.fill_gnl_stats(session, [player for player, _ in roster])


def _public(session: OrmSession, team: Team) -> TeamPublic:
    """One team, with its standings derived from the series it played."""
    public = TeamPublic.from_team(team)
    _fill(session, [public])
    return public


def _season_loads(season_id: int) -> list[Any]:
    """Loader options for one season of a team: roster, captains and stats."""
    roster = rel(Team.user_seasons).and_(col(DBUserTeamSeason.season_id) == season_id)
    info = rel(Team.season_info).and_(col(DBTeamSeason.season_id) == season_id)
    stats = rel(User.team_seasons).and_(col(DBUserTeamSeason.season_id) == season_id)
    seats = rel(Team.captain_seasons).and_(
        col(DBTeamSeasonCaptain.season_id) == season_id
    )
    return [
        joinedload(roster)
        .joinedload(rel(DBUserTeamSeason.user))
        .options(
            selectinload(rel(User.w3c_stats)),
            selectinload(stats),
            noload(rel(User.signup_seasons)),
        ),
        joinedload(roster).noload(rel(DBUserTeamSeason.team)),
        joinedload(info),
        joinedload(seats)
        .joinedload(rel(DBTeamSeasonCaptain.user))
        .options(
            selectinload(rel(User.w3c_stats)),
            noload(rel(User.team_seasons)),
            noload(rel(User.signup_seasons)),
        ),
    ]


# A team list reads the season rows and no people; noload alone, because a
# joined link table multiplies the rows.
_LIST_OPTIONS = (
    noload(rel(Team.user_seasons)),
    noload(rel(Team.captain_seasons)),
    selectinload(rel(Team.season_info)),
)


class TeamService:
    def __init__(self, user_app_service: UserService) -> None:
        self.user_app_service = user_app_service

    def legacy_gnl_league_id(self) -> int:
        """The GNL owner used only by the deprecated unscoped team create."""
        with Session.begin() as session:
            league = session.scalars(
                select(League).where(col(League.kind) == LeagueKind.gnl)
            ).first()
            if league is None:
                league = League(
                    name="GNL",
                    short_name="GNL",
                    kind=LeagueKind.gnl,
                    entrant_kind=EntrantKind.drafted_teams,
                )
                session.add(league)
                session.flush()
            return ident(league)

    def add(self, league_id: int, team: TeamCreate) -> TeamPublic:
        with Session.begin() as session:
            _league(session, league_id)
            new_team = Team.add(session, team.model_dump() | {"league_id": league_id})
            return _public(session, new_team)

    def update(
        self, team_id: int, team: TeamUpdate, league_id: int | None = None
    ) -> TeamPublic:
        with Session.begin() as session:
            row = _team(session, team_id, league_id)
            row.sqlmodel_update(team.model_dump(exclude_unset=True))
            session.flush()
            return _public(session, row)

    def update_icon(
        self, team_id: int, file: bytes, league_id: int | None = None
    ) -> None:
        """Put the logo in the store, then point the row at it and drop the one it replaced."""
        # at the boundary the bytes arrive at, so it holds whatever the store is or is stubbed to be
        blob.icon_type(file)
        # the store is not part of the transaction, so the put happens first: a put that is never
        # committed leaves an unreferenced blob, which is cheap, while a committed row pointing at
        # a blob that was never written is a broken image
        url = blob.put_icon(f"teams/{team_id}", file)
        with Session.begin() as session:
            # locked: two uploads for one team would otherwise read the same previous URL, and the
            # loser's blob would be left behind with nothing pointing at it
            team = session.get(Team, team_id, with_for_update=True)
            if not team or (league_id is not None and team.league_id != league_id):
                raise NotFoundError("Team not found")
            previous = team.icon_url
            team.icon_url = url
        if previous:
            blob.delete_blob(previous)

    def add_players(
        self, team_id: int, season_id: int, player_ids: list[int]
    ) -> TeamPublic:
        with Session.begin() as session:
            team, season = _event_team(session, team_id, season_id)
            for user_id in player_ids:
                user = session.get(User, user_id)
                if not user:
                    raise NotFoundError(f"User not found by id: {user_id}")
                try:
                    # The primary key decides: a duplicate link is already there
                    with session.begin_nested():
                        session.add(
                            DBUserTeamSeason(user=user, season=season, team=team)
                        )
                except IntegrityError:
                    logger.debug(f"User {user_id} is already in team {team_id}")
            session.flush()
            public = _public(session, team)

        discord_roles.sync(player_ids)
        return public

    def remove_players(
        self, team_id: int, season_id: int, player_ids: list[int]
    ) -> TeamPublic:
        with Session.begin() as session:
            team, _ = _event_team(session, team_id, season_id)
            for user_id in player_ids:
                user = session.get(User, user_id)
                if not user:
                    raise NotFoundError(f"User not found by id: {user_id}")
                user_team = session.get(
                    DBUserTeamSeason,
                    {"team_id": team_id, "season_id": season_id, "user_id": user.id},
                )
                if not user_team:
                    raise BadRequestError(
                        f"User not part of the team, user id: {user_id}"
                    )
                session.delete(user_team)
            session.flush()
            public = _public(session, team)

        discord_roles.sync(player_ids)
        return public

    def set_captains(
        self, team_id: int, season_id: int, captain_ids: list[int]
    ) -> TeamPublic:
        """Replace the captains a team has in a season. Any number of them."""
        with Session.begin() as session:
            team, _ = _event_team(session, team_id, season_id)

            for user_id in captain_ids:
                if not session.get(User, user_id):
                    raise NotFoundError(f"User not found by id: {user_id}")

            # A team fields a season even before it has a captain in it
            if not session.get(
                DBTeamSeason, {"team_id": team_id, "season_id": season_id}
            ):
                session.add(DBTeamSeason(team_id=team_id, season_id=season_id))

            before = {
                seat.user_id
                for seat in team.captain_seasons
                if seat.season_id == season_id
            }
            after = set(captain_ids)
            for user_id in before - after:
                session.delete(
                    session.get(
                        DBTeamSeasonCaptain,
                        {
                            "team_id": team_id,
                            "season_id": season_id,
                            "user_id": user_id,
                        },
                    )
                )
            for user_id in after - before:
                session.add(
                    DBTeamSeasonCaptain(
                        team_id=team_id, season_id=season_id, user_id=user_id
                    )
                )

            session.flush()
            # The rows were written by id, so the team reads its captains again
            session.expire(team, ["captain_seasons"])
            public = _public(session, team)

        # Discord mirrors the database, and the chip says what the guild lacks
        discord_roles.sync(before | after)
        public.discord_role_missing = [
            account.discord_id
            for account in discord_roles.report(after)
            if account.missing
        ]
        return public

    def captain_seats(self, discord_id: str) -> list[tuple[int, int]]:
        """Every (team, season) this Discord account captains, newest season first.

        A season that has run to its end carries no powers, so a complete
        season is left out; every other phase counts.
        """
        with Session.begin() as session:
            seats = session.execute(
                select(
                    col(DBTeamSeasonCaptain.team_id), col(DBTeamSeasonCaptain.season_id)
                )
                .join(User, col(DBTeamSeasonCaptain.user_id) == col(User.id))
                .where(col(User.discordId) == discord_id)
            ).all()
            if not seats:
                return []
            seasons = session.scalars(
                select(Season).where(
                    col(Season.id).in_({seat.season_id for seat in seats})
                )
            ).all()
            phases = progress_by_seasons(session, seasons)
            return sorted(
                (
                    (seat.team_id, seat.season_id)
                    for seat in seats
                    if phases[seat.season_id].phase != "complete"
                ),
                key=lambda seat: seat[1],
                reverse=True,
            )

    def player_teams(self, user_id: int) -> dict[int, tuple[int, str]]:
        """The team this player rosters for in each season: season id -> (id, name)."""
        with Session.begin() as session:
            rows = session.execute(
                select(col(DBUserTeamSeason.season_id), col(Team.id), col(Team.name))
                .join(Team, col(Team.id) == col(DBUserTeamSeason.team_id))
                .where(col(DBUserTeamSeason.user_id) == user_id)
            ).all()
            return {row[0]: (row[1], row[2]) for row in rows}

    def delete(self, team_id: int, league_id: int | None = None) -> None:
        with Session.begin() as session:
            session.delete(_team(session, team_id, league_id))

    def get(self, team_id: int, league_id: int | None = None) -> TeamPublic:
        with Session.begin() as session:
            # Eager load related entities, disable nested loading
            team = (
                session.scalars(
                    select(Team)
                    .options(
                        joinedload(rel(Team.user_seasons)).noload("*"),
                        joinedload(rel(Team.captain_seasons)).joinedload(
                            rel(DBTeamSeasonCaptain.user)
                        ),
                    )
                    .where(
                        col(Team.id) == team_id,
                        col(Team.league_id) == league_id
                        if league_id is not None
                        else true(),
                    )
                )
                .unique()
                .first()
            )
            if not team:
                raise NotFoundError("Team not found")
            return _public(session, team)

    def get_with_nested_users_by_season(
        self, team_id: int, season_id: int
    ) -> TeamPublic:
        """One team with the season's roster, captains and stats."""
        with Session.begin() as session:
            _event_team(session, team_id, season_id)
            team = (
                session.scalars(
                    select(Team)
                    .where(col(Team.id) == team_id)
                    .options(*_season_loads(season_id))
                )
                .unique()
                .first()
            )
            if not team:
                raise NotFoundError("Team not found")
            return _public(session, team)

    def ensure_event_team(self, team_id: int, event_id: int) -> None:
        """Refuse a team that is not entered in this event or its league."""
        with Session.begin() as session:
            _event_team(session, team_id, event_id)

    def get_icon_url(self, team_id: int, league_id: int | None = None) -> str | None:
        """Where the logo lives, or None for a team without one."""
        with Session.begin() as session:
            return _team(session, team_id, league_id).icon_url

    def search(
        self,
        query: QueryElement | None,
        limit: int | None = None,
        offset: int = 0,
        league_id: int | None = None,
    ) -> list[TeamPublic]:
        filter = QueryUtil.convert_query_to_db_filter(Team, query)
        if filter is None:
            return []
        with Session.begin() as session:
            if league_id is not None:
                _league(session, league_id)
            # Offset paging is deterministic only with a fixed order
            statement = (
                select(Team)
                .options(*_LIST_OPTIONS)
                .where(
                    filter,
                    col(Team.league_id) == league_id
                    if league_id is not None
                    else true(),
                )
                .order_by(col(Team.id))
                .offset(offset)
                .limit(limit)
            )
            teams = session.scalars(statement).unique().all()
            result = [TeamPublic.from_team(team) for team in teams]
            _fill(session, result)
            return result

    def get_all(
        self,
        limit: int | None = None,
        offset: int = 0,
        league_id: int | None = None,
    ) -> list[TeamPublic]:
        with Session.begin() as session:
            if league_id is not None:
                _league(session, league_id)
            # Offset paging is deterministic only with a fixed order
            statement = (
                select(Team)
                .options(*_LIST_OPTIONS)
                .where(
                    col(Team.league_id) == league_id
                    if league_id is not None
                    else true()
                )
                .order_by(col(Team.id))
                .offset(offset)
                .limit(limit)
            )
            teams = session.scalars(statement).unique().all()
            result = [TeamPublic.from_team(team) for team in teams]
            _fill(session, result)
            return result

    def get_all_basic(
        self,
        limit: int | None = None,
        offset: int = 0,
        league_id: int | None = None,
    ) -> list[TeamPublic]:
        """Get all teams with basic info only (no users, no seasons)"""
        with Session.begin() as session:
            if league_id is not None:
                _league(session, league_id)
            # noload("*") keeps every relationship out
            # Offset paging is deterministic only with a fixed order
            statement = (
                select(Team)
                .options(noload("*"))
                .where(
                    col(Team.league_id) == league_id
                    if league_id is not None
                    else true()
                )
                .order_by(col(Team.id))
                .offset(offset)
                .limit(limit)
            )
            teams = session.scalars(statement).unique().all()
            result = [TeamPublic.from_team(team) for team in teams]
            _fill(session, result)
            return result

    def get_teams_season(
        self, season_id: int, limit: int | None = None, offset: int = 0
    ) -> list[TeamPublic]:
        """The season's teams with the season's rosters and captains.

        The season sits in the query, so only that season's link rows
        load. Roster and captain users answer empty signup_seasons, and
        captains empty gnl_stats; no consumer reads them on this route.
        """
        with Session.begin() as session:
            if session.get(Season, season_id) is None:
                raise NotFoundError(f"Event not found by id: {season_id}")
            # Offset paging is deterministic only with a fixed order
            statement = (
                select(Team)
                .where(
                    col(Team.season_info).any(col(DBTeamSeason.season_id) == season_id)
                )
                .options(*_season_loads(season_id))
                .order_by(col(Team.id))
                .offset(offset)
                .limit(limit)
            )
            teams = session.scalars(statement).unique().all()
            result = [TeamPublic.from_team(team) for team in teams]
            _fill(session, result)
            return result

    def get_teams_season_basic(
        self, season_id: int, limit: int | None = None, offset: int = 0
    ) -> list[TeamPublic]:
        """The season's teams with that season's info and no users, for list views.

        The season sits in the loader, so seasons_info holds that season alone.
        """
        with Session.begin() as session:
            if session.get(Season, season_id) is None:
                raise NotFoundError(f"Event not found by id: {season_id}")
            info = rel(Team.season_info).and_(col(DBTeamSeason.season_id) == season_id)
            # An EXISTS, not a join: a join multiplies the rows a page counts
            # Offset paging is deterministic only with a fixed order
            statement = (
                select(Team)
                .options(
                    noload(rel(Team.user_seasons)),
                    noload(rel(Team.captain_seasons)),
                    joinedload(info).noload("*"),
                )
                .where(col(Team.season_info).any(season_id=season_id))
                .order_by(col(Team.id))
                .offset(offset)
                .limit(limit)
            )
            teams = session.scalars(statement).unique().all()
            result = [TeamPublic.from_team(team) for team in teams]
            _fill(session, result)
            return result

    def season_players(self, team_id: int, season_id: int) -> list[UserPublic]:
        """The players this team fielded in this season."""
        team = self.get_with_nested_users_by_season(team_id, season_id)
        return team.player_by_season.get(season_id) or []
