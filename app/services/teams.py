import logging
from collections.abc import Sequence

from sqlalchemy import select, true
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import joinedload, noload, selectinload
from sqlalchemy.orm.strategy_options import _AbstractLoad
from sqlmodel import col

from app.core.db import Session, rel
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.query import QueryElement, QueryUtil
from app.models.base import ident
from app.models.league import League
from app.models.relationships import DBTeamSeasonCaptain
from app.models.season import Season, progress_by_seasons
from app.models.team import Team, TeamCreate, TeamPublic, TeamRosterPublic, TeamUpdate
from app.models.team_season import DBTeamSeason
from app.models.user import User, UserSummaryPublic
from app.models.user_team_season import DBUserTeamSeason
from app.services import availability, blob, derived, discord_roles
from app.services.users import UserService, summary_loads
from app.services.w3c_stats import fill, w3c_season

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
    """A team of the event's league. No link row is required: a cup or a clan
    war holds its teams as event entrants, and a roster write is often the
    first link the team gets."""
    event = session.get(Season, event_id)
    if not event:
        raise NotFoundError(f"Event not found by id: {event_id}")
    team = _team(session, team_id)
    if team.league_id != event.league_id:
        raise NotFoundError("Team not found in event")
    return team, event


def roster_loads(event_id: int) -> tuple[_AbstractLoad, ...]:
    """The loads of one event's roster, relative to a Team: its players and
    captains of `event_id` with their summary rows, and its row of that event."""
    players = rel(Team.user_seasons).and_(col(DBUserTeamSeason.season_id) == event_id)
    seats = rel(Team.captain_seasons).and_(
        col(DBTeamSeasonCaptain.season_id) == event_id
    )
    info = rel(Team.season_info).and_(col(DBTeamSeason.season_id) == event_id)
    return (
        joinedload(players)
        .joinedload(rel(DBUserTeamSeason.user))
        .options(*summary_loads(event_id)),
        selectinload(seats)
        .joinedload(rel(DBTeamSeasonCaptain.user))
        .options(*summary_loads(event_id)),
        joinedload(info),
    )


def _fill(session: OrmSession, teams: Sequence[TeamPublic]) -> None:
    """The standings of every team and the name and league of every season it
    played."""
    derived.fill_standings(session, teams)
    derived.fill_season_labels(session, teams)


def _rosters(
    session: OrmSession, teams: Sequence[Team], event_id: int
) -> list[TeamRosterPublic]:
    """The teams with their roster of the event, as roster_loads read them: the
    standings, then for every player and captain the signup race, the MMR he
    entered a finished event with, his event record and his ladder summary."""
    result = [TeamRosterPublic.from_roster(team, event_id) for team in teams]
    _fill(session, result)
    people = [
        user
        for team in result
        for seats in (team.player_by_season, team.captains_by_season)
        for users in seats.values()
        for user in users
    ]
    derived.fill_user_signup_races(
        session, [(user, event_id) for user in people], entered=True
    )
    derived.fill_gnl_stats(session, people)
    fill(session, people, w3c_season(session))
    return result


def _fill_out_rounds(
    session: OrmSession, public: TeamRosterPublic, team_id: int, season_id: int
) -> None:
    """The rounds each roster player sits out of the event, on their event record.

    A fixed number of statements answers the whole roster, never one per player.
    """
    out = availability.out_rounds(session, team_id, season_id)
    for player in public.player_by_season.get(season_id) or []:
        if player.record and player.id in out:
            player.record.out_rounds = out[player.id]


class TeamService:
    def __init__(self, user_app_service: UserService) -> None:
        self.user_app_service = user_app_service

    def add(self, league_id: int, team: TeamCreate) -> TeamPublic:
        with Session.begin() as session:
            _league(session, league_id)
            new_team = Team.add(session, team.model_dump() | {"league_id": league_id})
            team_id = ident(new_team)
        return self.get(team_id, league_id)

    def update(
        self, team_id: int, team: TeamUpdate, league_id: int | None = None
    ) -> TeamPublic:
        with Session.begin() as session:
            row = _team(session, team_id, league_id)
            row.sqlmodel_update(team.model_dump(exclude_unset=True))
        return self.get(team_id, league_id)

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
    ) -> TeamRosterPublic:
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

        discord_roles.sync(player_ids)
        return self.get_with_nested_users_by_season(team_id, season_id)

    def remove_players(
        self, team_id: int, season_id: int, player_ids: list[int]
    ) -> TeamRosterPublic:
        with Session.begin() as session:
            _event_team(session, team_id, season_id)
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

        discord_roles.sync(player_ids)
        return self.get_with_nested_users_by_season(team_id, season_id)

    def set_captains(
        self, team_id: int, season_id: int, captain_ids: list[int]
    ) -> TeamRosterPublic:
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

        # Discord mirrors the database, and the chip says what the guild lacks
        discord_roles.sync(before | after)
        public = self.get_with_nested_users_by_season(team_id, season_id)
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
            team = session.scalars(
                select(Team)
                .options(selectinload(rel(Team.season_info)))
                .where(
                    col(Team.id) == team_id,
                    col(Team.league_id) == league_id
                    if league_id is not None
                    else true(),
                )
            ).first()
            if not team:
                raise NotFoundError("Team not found")
            public = TeamPublic.from_team(team)
            _fill(session, [public])
            return public

    def get_with_nested_users_by_season(
        self, team_id: int, season_id: int
    ) -> TeamRosterPublic:
        """One team with the season's roster, captains, stats and sat-out rounds."""
        with Session.begin() as session:
            _, event = _event_team(session, team_id, season_id)
            team = (
                session.scalars(
                    select(Team)
                    .where(col(Team.id) == team_id)
                    .options(*roster_loads(season_id))
                )
                .unique()
                .first()
            )
            if not team:
                raise NotFoundError("Team not found")
            [public] = _rosters(session, [team], season_id)
            # An event without scheduling asks nobody, so every list stays empty
            if event.scheduling_enabled:
                _fill_out_rounds(session, public, team_id, season_id)
            return public

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
            # Offset paging is deterministic only with a fixed order
            statement = (
                select(Team)
                .options(selectinload(rel(Team.season_info)))
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
            # Offset paging is deterministic only with a fixed order
            statement = (
                select(Team)
                .options(selectinload(rel(Team.season_info)))
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
    ) -> list[TeamRosterPublic]:
        """The season's teams with the season's rosters and captains.

        The season sits in the loader, so only that season's link rows load.
        """
        with Session.begin() as session:
            # Offset paging is deterministic only with a fixed order
            statement = (
                select(Team)
                .where(
                    col(Team.season_info).any(col(DBTeamSeason.season_id) == season_id)
                )
                .options(*roster_loads(season_id))
                .order_by(col(Team.id))
                .offset(offset)
                .limit(limit)
            )
            teams = session.scalars(statement).unique().all()
            return _rosters(session, teams, season_id)

    def get_teams_season_basic(
        self, season_id: int, limit: int | None = None, offset: int = 0
    ) -> list[TeamPublic]:
        """The season's teams with that season's info and no users, for list views.

        The season sits in the loader, so seasons_info holds that season alone.
        """
        with Session.begin() as session:
            info = rel(Team.season_info).and_(col(DBTeamSeason.season_id) == season_id)
            # An EXISTS, not a join: a join multiplies the rows a page counts
            # Offset paging is deterministic only with a fixed order
            statement = (
                select(Team)
                .options(joinedload(info))
                .where(col(Team.season_info).any(season_id=season_id))
                .order_by(col(Team.id))
                .offset(offset)
                .limit(limit)
            )
            teams = session.scalars(statement).unique().all()
            result = [TeamPublic.from_team(team) for team in teams]
            _fill(session, result)
            return result

    def season_players(self, team_id: int, season_id: int) -> list[UserSummaryPublic]:
        """The players this team fielded in this season."""
        team = self.get_with_nested_users_by_season(team_id, season_id)
        return team.player_by_season.get(season_id) or []
