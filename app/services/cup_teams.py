"""The teams of a team cup: made for one cup, signed up by a captain, confirmed
by every player they invite.

A cup team is a team row with the cup as its `event_id`; its roster
(user_team_season against the cup) holds confirmed players only, its captain
sits in team_season_captain, and an invited player waits in team_invite. The
engine plays the team's entrant as any team entrant: the roster fills the side.
Every player is held to the cup's eligibility on their own.
"""

from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col, or_

from app.core.db import Session
from app.core.exceptions import ApiError, BadRequestError, NotFoundError
from app.models.base import ident
from app.models.enums import EntrantKind
from app.models.event_entrant import EntrantAdd, EventEntrant, EventEntrantPublic
from app.models.relationships import DBEventRound, DBTeamSeasonCaptain
from app.models.season import Season
from app.models.series import Series
from app.models.series_side import SeriesSide
from app.models.series_veto_step import DBSeriesVetoStep
from app.models.team import Team
from app.models.team_invite import (
    CupTeamAdd,
    CupTeamCreate,
    TeamInvite,
    TeamInvitePublic,
)
from app.models.team_season import DBTeamSeason
from app.models.team_summary import TeamSummaryPublic
from app.models.types import utcnow
from app.models.user import User, UserSummaryPublic
from app.models.user_team_season import DBUserTeamSeason
from app.services import events as event_service
from app.services import stage_engine


def sign_up(
    event_id: int, data: CupTeamCreate, claims: dict[str, Any] | None
) -> EventEntrantPublic:
    """The caller signs a team up: they captain it, and every other player is invited."""
    _refresh(event_id, data.member_ids)
    with Session.begin() as session:
        event = _team_cup(session, event_id)
        if not event_service._signups_open(
            event, event_service.phase_of(session, event)
        ):
            raise BadRequestError("Signups are closed for this event")
        captain = event_service._caller(session, claims)
        if captain is None:
            raise ApiError(
                403, {"error": "No player profile is linked to this Discord account"}
            )
        others = _others(data.member_ids, ident(captain))
        if len(others) + 1 != event.team_size:
            raise BadRequestError(
                f"A team of this cup fields {event.team_size} players: you and "
                f"{(event.team_size or 1) - 1} more"
            )
        players = _players(session, [ident(captain), *others])
        _hold_free(session, event, players)
        for player in players:
            _hold(session, event, player)
        row = _write_team(
            session, event, data.name, captain, confirmed=[], invited=others
        )
        return event_service._entrant_publics(session, event, [row])[0]


def add_by_hand(event_id: int, data: CupTeamAdd) -> EventEntrantPublic:
    """A runner enters a whole team at once: every player confirmed, whether
    signups stand open or not, each held to the cup's eligibility."""
    _refresh(event_id, [data.captain_id, *data.member_ids])
    with Session.begin() as session:
        event = _team_cup(session, event_id)
        others = _others(data.member_ids, data.captain_id)
        if len(others) + 1 != event.team_size:
            raise BadRequestError(
                f"A team of this cup fields {event.team_size} players, captain included"
            )
        players = _players(session, [data.captain_id, *others])
        _hold_free(session, event, players)
        for player in players:
            _hold(session, event, player)
        row = _write_team(
            session, event, data.name, players[0], confirmed=others, invited=[]
        )
        return event_service._entrant_publics(session, event, [row])[0]


def accept(event_id: int, team_id: int, claims: dict[str, Any] | None) -> None:
    """The invited player joins the roster, held to the cup's eligibility again."""
    with Session.begin() as session:
        caller = event_service._caller(session, claims)
        user_id = ident(caller) if caller is not None else None
    if user_id is None:
        raise ApiError(
            403, {"error": "No player profile is linked to this Discord account"}
        )
    _refresh(event_id, [user_id])
    with Session.begin() as session:
        event = _team_cup(session, event_id)
        invite = _invite(session, event_id, team_id, user_id)
        _hold(session, event, _players(session, [user_id])[0])
        session.delete(invite)
        session.add(
            DBUserTeamSeason(user_id=user_id, team_id=team_id, season_id=event_id)
        )


def decline(event_id: int, team_id: int, claims: dict[str, Any] | None) -> None:
    """The invited player says no; the captain may invite someone else."""
    with Session.begin() as session:
        caller = event_service._caller(session, claims)
        if caller is None:
            raise ApiError(
                403, {"error": "No player profile is linked to this Discord account"}
            )
        session.delete(_invite(session, event_id, team_id, ident(caller)))


def invite(
    event_id: int, team_id: int, user_id: int, claims: dict[str, Any] | None
) -> None:
    """The captain invites one more player into a place the team has free."""
    _refresh(event_id, [user_id])
    with Session.begin() as session:
        event = _team_cup(session, event_id)
        _hold_captain(session, event_id, team_id, claims)
        held = _roster_count(session, event_id, team_id) + _invite_count(
            session, team_id
        )
        if held >= (event.team_size or 0):
            raise BadRequestError("The team is full; take an invite back first")
        players = _players(session, [user_id])
        _hold_free(session, event, players)
        _hold(session, event, players[0])
        session.add(TeamInvite(team_id=team_id, user_id=user_id, event_id=event_id))


def take_back(
    event_id: int, team_id: int, user_id: int, claims: dict[str, Any] | None
) -> None:
    """The captain takes an invite back that is still unanswered."""
    with Session.begin() as session:
        _hold_captain(session, event_id, team_id, claims)
        session.delete(_invite(session, event_id, team_id, user_id))


def leave(event_id: int, team_id: int, claims: dict[str, Any] | None) -> None:
    """A player who is not the captain leaves the team before it plays."""
    with Session.begin() as session:
        caller = event_service._caller(session, claims)
        if caller is None:
            raise ApiError(
                403, {"error": "No player profile is linked to this Discord account"}
            )
        if session.get(DBTeamSeasonCaptain, (team_id, event_id, ident(caller))):
            raise BadRequestError("The captain withdraws the team instead")
        row = session.get(DBUserTeamSeason, (ident(caller), team_id, event_id))
        if row is None:
            raise NotFoundError("You are not in this team")
        _hold_unplayed(session, _entrant_of(session, event_id, team_id))
        session.delete(row)


def withdraw(event_id: int, team_id: int, claims: dict[str, Any] | None) -> None:
    """The captain withdraws the team; its open invites go with it, and on a
    drawn cup it forfeits every series it still owes."""
    with Session.begin() as session:
        _hold_captain(session, event_id, team_id, claims)
        entrant = _entrant_of(session, event_id, team_id)
        entrant.withdrawn_at = utcnow()
        session.execute(delete(TeamInvite).where(col(TeamInvite.team_id) == team_id))
        session.flush()
        stage_engine.forfeit_open(session, [ident(entrant)])


def replace_member(
    event_id: int, team_id: int, user_id: int, data_user_id: int
) -> EventEntrantPublic:
    """A runner puts another player in a team's place of one who leaves it.

    The new player takes the old one's seat on the roster, the captaincy with
    it, and their place on every series the team has still to play, whose veto
    starts over. A team that has played a match keeps its roster.
    """
    _refresh(event_id, [data_user_id])
    with Session.begin() as session:
        event = _team_cup(session, event_id)
        entrant = _entrant_of(session, event_id, team_id)
        _hold_unplayed(session, entrant)
        row = session.get(DBUserTeamSeason, (user_id, team_id, event_id))
        if row is None:
            raise NotFoundError("That player is not in this team")
        players = _players(session, [data_user_id])
        _hold_free(session, event, players)
        _hold(session, event, players[0])
        session.delete(row)
        session.add(
            DBUserTeamSeason(user_id=data_user_id, team_id=team_id, season_id=event_id)
        )
        captain = session.get(DBTeamSeasonCaptain, (team_id, event_id, user_id))
        if captain is not None:
            session.delete(captain)
            session.add(
                DBTeamSeasonCaptain(
                    team_id=team_id, season_id=event_id, user_id=data_user_id
                )
            )
        for side in session.scalars(
            select(SeriesSide).where(
                col(SeriesSide.entrant_id) == ident(entrant),
                col(SeriesSide.user_id) == user_id,
            )
        ).all():
            series = session.get(Series, side.series_id)
            if series is None or stage_engine.scored(series):
                continue
            session.add(
                SeriesSide(
                    series_id=side.series_id,
                    side_no=side.side_no,
                    user_id=data_user_id,
                    entrant_id=side.entrant_id,
                    place=side.place,
                )
            )
            session.delete(side)
            session.execute(
                delete(DBSeriesVetoStep).where(
                    col(DBSeriesVetoStep.series_id) == side.series_id
                )
            )
        session.flush()
        return event_service._entrant_publics(session, event, [entrant])[0]


def invites_for(claims: dict[str, Any] | None) -> list[TeamInvitePublic]:
    """The invitations the caller has not answered, newest first."""
    with Session.begin() as session:
        caller = event_service._caller(session, claims)
        if caller is None:
            return []
        rows = session.execute(
            select(TeamInvite, Team, Season)
            .join(Team, col(Team.id) == col(TeamInvite.team_id))
            .join(Season, col(Season.id) == col(TeamInvite.event_id))
            .where(col(TeamInvite.user_id) == ident(caller))
            .order_by(col(TeamInvite.invited_at).desc())
        ).all()
        captains = {
            team_id: user
            for team_id, user in session.execute(
                select(col(DBTeamSeasonCaptain.team_id), User)
                .join(User, col(User.id) == col(DBTeamSeasonCaptain.user_id))
                .where(
                    col(DBTeamSeasonCaptain.team_id).in_(
                        [ident(team) for _, team, _ in rows]
                    )
                )
            ).all()
        }
        return [
            TeamInvitePublic(
                event_id=ident(event),
                event_name=event.name,
                team=TeamSummaryPublic.from_team(team),
                captain=UserSummaryPublic.from_user(captains[ident(team)])
                if ident(team) in captains
                else None,
                invited_at=invite.invited_at,
            )
            for invite, team, event in rows
        ]


def incomplete(session: OrmSession, event: Season) -> list[str]:
    """The names of the teams still in a cup whose roster is short of the team size."""
    if not event.team_size:
        return []
    counts: dict[int, int] = {
        team_id: total
        for team_id, total in session.execute(
            select(col(DBUserTeamSeason.team_id), func.count())
            .where(col(DBUserTeamSeason.season_id) == ident(event))
            .group_by(col(DBUserTeamSeason.team_id))
        ).all()
    }
    teams = session.execute(
        select(col(Team.id), col(Team.name))
        .join(EventEntrant, col(EventEntrant.team_id) == col(Team.id))
        .where(
            col(EventEntrant.event_id) == ident(event),
            col(EventEntrant.withdrawn_at).is_(None),
        )
    ).all()
    return [name for team_id, name in teams if counts.get(team_id, 0) < event.team_size]


def _team_cup(session: OrmSession, event_id: int) -> Season:
    event = event_service._event(session, event_id)
    if not event.team_size:
        raise BadRequestError("This event is played one against one, not in teams")
    return event


def _others(member_ids: list[int], captain_id: int) -> list[int]:
    """The players besides the captain, each named once."""
    others = list(
        dict.fromkeys(member for member in member_ids if member != captain_id)
    )
    if len(others) != len([member for member in member_ids if member != captain_id]):
        raise BadRequestError("Name each player once")
    return others


def _players(session: OrmSession, user_ids: list[int]) -> list[User]:
    found = {
        ident(user): user
        for user in session.scalars(select(User).where(col(User.id).in_(user_ids)))
    }
    missing = [user_id for user_id in user_ids if user_id not in found]
    if missing:
        raise NotFoundError(f"User not found by id: {missing[0]}")
    return [found[user_id] for user_id in user_ids]


def _hold_free(session: OrmSession, event: Season, players: list[User]) -> None:
    """Refuse a player who already plays for, or is invited by, a team of this cup."""
    ids = [ident(player) for player in players]
    taken = set(
        session.scalars(
            select(col(DBUserTeamSeason.user_id))
            .join(
                EventEntrant,
                (col(EventEntrant.team_id) == col(DBUserTeamSeason.team_id))
                & (col(EventEntrant.event_id) == col(DBUserTeamSeason.season_id)),
            )
            .where(
                col(DBUserTeamSeason.season_id) == ident(event),
                col(DBUserTeamSeason.user_id).in_(ids),
                col(EventEntrant.withdrawn_at).is_(None),
            )
        )
    ) | set(
        session.scalars(
            select(col(TeamInvite.user_id)).where(
                col(TeamInvite.event_id) == ident(event),
                col(TeamInvite.user_id).in_(ids),
            )
        )
    )
    names = [player.name for player in players if ident(player) in taken]
    if names:
        raise BadRequestError(
            f"{', '.join(names)} already plays for a team of this cup"
        )


def _hold(session: OrmSession, event: Season, player: User) -> None:
    """Hold one player to the cup's eligibility, on their own."""
    if event.eligibility_required:
        event_service._hold_eligible(session, event, ident(player), player.race)


def _refresh(event_id: int, user_ids: list[int]) -> None:
    """Ask W3Champions about each player first, as a signup of one player does."""
    for user_id in dict.fromkeys(user_ids):
        event_service._refresh_for(event_id, EntrantAdd(user_id=user_id), None)


def _write_team(
    session: OrmSession,
    event: Season,
    name: str,
    captain: User,
    confirmed: list[int],
    invited: list[int],
) -> EventEntrant:
    """The cup team, its roster, its captain, its invites and its entrant."""
    if event.entrant_kind is not EntrantKind.team:
        event.entrant_kind = EntrantKind.team
    event_service._room_for_one_more(session, event)
    team = Team(name=name.strip(), event_id=ident(event), league_id=event.league_id)
    session.add(team)
    session.flush()
    team_id = ident(team)
    session.add(DBTeamSeason(team_id=team_id, season_id=ident(event)))
    session.add(
        DBTeamSeasonCaptain(
            team_id=team_id, season_id=ident(event), user_id=ident(captain)
        )
    )
    for user_id in [ident(captain), *confirmed]:
        session.add(
            DBUserTeamSeason(user_id=user_id, team_id=team_id, season_id=ident(event))
        )
    for user_id in invited:
        session.add(TeamInvite(team_id=team_id, user_id=user_id, event_id=ident(event)))
    row = EventEntrant(event_id=ident(event), team_id=team_id)
    session.add(row)
    session.flush()
    return row


def _invite(
    session: OrmSession, event_id: int, team_id: int, user_id: int
) -> TeamInvite:
    row = session.get(TeamInvite, (team_id, user_id))
    if row is None or row.event_id != event_id:
        raise NotFoundError("No invite of this team for that player")
    return row


def _hold_captain(
    session: OrmSession, event_id: int, team_id: int, claims: dict[str, Any] | None
) -> None:
    caller = event_service._caller(session, claims)
    if caller is None or not session.get(
        DBTeamSeasonCaptain, (team_id, event_id, ident(caller))
    ):
        raise ApiError(403, {"error": "Only the captain of the team does this"})


def _roster_count(session: OrmSession, event_id: int, team_id: int) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(DBUserTeamSeason)
            .where(
                col(DBUserTeamSeason.team_id) == team_id,
                col(DBUserTeamSeason.season_id) == event_id,
            )
        )
        or 0
    )


def _invite_count(session: OrmSession, team_id: int) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(TeamInvite)
            .where(col(TeamInvite.team_id) == team_id)
        )
        or 0
    )


def _entrant_of(session: OrmSession, event_id: int, team_id: int) -> EventEntrant:
    row = session.scalars(
        select(EventEntrant).where(
            col(EventEntrant.event_id) == event_id,
            col(EventEntrant.team_id) == team_id,
        )
    ).first()
    if row is None:
        raise NotFoundError(f"Team not found in this event by id: {team_id}")
    return row


def _hold_unplayed(session: OrmSession, entrant: EventEntrant) -> None:
    """Refuse a change of roster once the team has played a match."""
    entrant_id = ident(entrant)
    played = session.scalars(
        select(Series)
        .join(DBEventRound, col(DBEventRound.id) == col(Series.round_id))
        .where(
            or_(
                col(Series.entrant1_id) == entrant_id,
                col(Series.entrant2_id) == entrant_id,
            ),
            col(Series.entrant1_id).is_not(None),
            col(Series.entrant2_id).is_not(None),
        )
    ).all()
    if any(stage_engine.scored(row) for row in played):
        raise BadRequestError(
            "This team has played a match already, so its roster stays"
        )
