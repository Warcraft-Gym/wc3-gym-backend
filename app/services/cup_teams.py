"""The teams of a team cup: made for one cup, signed up by a captain, confirmed
by every player they invite.

A cup team is a `cup_team` row of the cup; its members (`cup_team_member`)
are the confirmed players, the captain among them, and an invited player
waits in `cup_team_invite`. No GNL read sees it. The engine plays the team's
entrant as one side, and every member acts for it. Every player is held to
the cup's eligibility on their own.
"""

from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col, or_

from app.core.db import Session
from app.core.exceptions import ApiError, BadRequestError, NotFoundError
from app.core.outcome import scored
from app.models.base import ident
from app.models.cup_series import CupSeries
from app.models.cup_team import (
    CupTeam,
    CupTeamAdd,
    CupTeamCreate,
    CupTeamInvite,
    CupTeamMember,
    TeamInvitePublic,
    team_summary,
)
from app.models.enums import EntrantKind
from app.models.event_entrant import EntrantAdd, EventEntrant, EventEntrantPublic
from app.models.season import Season
from app.models.types import utcnow
from app.models.user import User, UserSummaryPublic
from app.services import cup_engine
from app.services import events as event_service


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
            session,
            event,
            data.name,
            captain,
            confirmed=[],
            invited=others,
            may_wait=True,
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
        session.add(CupTeamMember(team_id=team_id, user_id=user_id))


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
        held = _roster_count(session, team_id) + _invite_count(session, team_id)
        if held >= (event.team_size or 0):
            raise BadRequestError("The team is full; take an invite back first")
        players = _players(session, [user_id])
        _hold_free(session, event, players)
        _hold(session, event, players[0])
        session.add(CupTeamInvite(team_id=team_id, user_id=user_id, event_id=event_id))


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
        entrant = _entrant_of(session, event_id, team_id)
        row = session.get(CupTeamMember, (team_id, ident(caller)))
        if row is None:
            raise NotFoundError("You are not in this team")
        if row.captain:
            raise BadRequestError("The captain withdraws the team instead")
        _hold_unplayed(session, entrant)
        session.delete(row)


def withdraw(event_id: int, team_id: int, claims: dict[str, Any] | None) -> None:
    """The captain withdraws the team; its open invites go with it, and on a
    drawn cup it forfeits every series it still owes."""
    with Session.begin() as session:
        _hold_captain(session, event_id, team_id, claims)
        entrant = _entrant_of(session, event_id, team_id)
        entrant.withdrawn_at = utcnow()
        session.execute(
            delete(CupTeamInvite).where(col(CupTeamInvite.team_id) == team_id)
        )
        session.flush()
        cup_engine.forfeit_open(session, [ident(entrant)])


def replace_member(
    event_id: int, team_id: int, user_id: int, data_user_id: int
) -> EventEntrantPublic:
    """A runner puts another player in a team's place of one who leaves it.

    The new player takes the old one's seat on the roster, and the captaincy
    with it. A team that has played a match keeps its roster.
    """
    _refresh(event_id, [data_user_id])
    with Session.begin() as session:
        event = _team_cup(session, event_id)
        entrant = _entrant_of(session, event_id, team_id)
        _hold_unplayed(session, entrant)
        row = session.get(CupTeamMember, (team_id, user_id))
        if row is None:
            raise NotFoundError("That player is not in this team")
        players = _players(session, [data_user_id])
        _hold_free(session, event, players)
        _hold(session, event, players[0])
        captain = row.captain
        session.delete(row)
        session.flush()
        session.add(
            CupTeamMember(team_id=team_id, user_id=data_user_id, captain=captain)
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
            select(CupTeamInvite, CupTeam, Season)
            .join(CupTeam, col(CupTeam.id) == col(CupTeamInvite.team_id))
            .join(Season, col(Season.id) == col(CupTeamInvite.event_id))
            .where(col(CupTeamInvite.user_id) == ident(caller))
            .order_by(col(CupTeamInvite.invited_at).desc())
        ).all()
        captains = {
            team_id: user
            for team_id, user in session.execute(
                select(col(CupTeamMember.team_id), User)
                .join(User, col(User.id) == col(CupTeamMember.user_id))
                .where(
                    col(CupTeamMember.team_id).in_(
                        [ident(team) for _, team, _ in rows]
                    ),
                    col(CupTeamMember.captain),
                )
            ).all()
        }
        return [
            TeamInvitePublic(
                event_id=ident(event),
                event_name=event.name,
                team=team_summary(team),
                captain=UserSummaryPublic.from_user(captains[ident(team)])
                if ident(team) in captains
                else None,
                invited_at=invite.invited_at,
            )
            for invite, team, event in rows
        ]


def incomplete(session: OrmSession, event: Season) -> list[str]:
    """The names of the teams the draw would seat whose roster is short of the
    team size. A cup that takes check-in seats the teams that checked in, and a
    short team cannot check in, so it is left out instead of holding the draw."""
    if not event.team_size:
        return []
    counts: dict[int, int] = {
        team_id: total
        for team_id, total in session.execute(
            select(col(CupTeamMember.team_id), func.count())
            .join(CupTeam, col(CupTeam.id) == col(CupTeamMember.team_id))
            .where(col(CupTeam.event_id) == ident(event))
            .group_by(col(CupTeamMember.team_id))
        ).all()
    }
    teams = session.execute(
        select(col(CupTeam.id), col(CupTeam.name))
        .join(EventEntrant, col(EventEntrant.cup_team_id) == col(CupTeam.id))
        .where(
            col(EventEntrant.event_id) == ident(event),
            col(EventEntrant.withdrawn_at).is_(None),
            col(EventEntrant.waitlisted_at).is_(None),
            *(
                [col(EventEntrant.checked_in_at).is_not(None)]
                if event.checkin_enabled
                else []
            ),
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
            select(col(CupTeamMember.user_id))
            .join(
                EventEntrant,
                col(EventEntrant.cup_team_id) == col(CupTeamMember.team_id),
            )
            .where(
                col(EventEntrant.event_id) == ident(event),
                col(CupTeamMember.user_id).in_(ids),
                col(EventEntrant.withdrawn_at).is_(None),
            )
        )
    ) | set(
        session.scalars(
            select(col(CupTeamInvite.user_id)).where(
                col(CupTeamInvite.event_id) == ident(event),
                col(CupTeamInvite.user_id).in_(ids),
            )
        )
    )
    names = [player.name for player in players if ident(player) in taken]
    if names:
        raise BadRequestError(
            f"{', '.join(names)} already plays for a team of this cup"
        )


def _hold(session: OrmSession, event: Season, player: User) -> None:
    """Hold one player to the cup's rules, on their own: a Discord login on a
    cup that takes members, a verified main tag where it asks, the rating."""
    event_service._hold_member(event, player)
    if event.bnet_required:
        event_service._hold_verified(session, ident(player))
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
    may_wait: bool = False,
) -> EventEntrant:
    """The cup team, its roster, its captain, its invites and its entrant.
    A captain's signup to a cup that is drawn or full waits on its waitlist."""
    if event.entrant_kind is not EntrantKind.team:
        event.entrant_kind = EntrantKind.team
    waits = may_wait and event_service._waits(session, event)
    if not waits:
        event_service._room_for_one_more(session, event)
    team = CupTeam(name=name.strip(), event_id=ident(event))
    session.add(team)
    session.flush()
    team_id = ident(team)
    session.add(CupTeamMember(team_id=team_id, user_id=ident(captain), captain=True))
    for user_id in confirmed:
        session.add(CupTeamMember(team_id=team_id, user_id=user_id))
    for user_id in invited:
        session.add(
            CupTeamInvite(team_id=team_id, user_id=user_id, event_id=ident(event))
        )
    row = EventEntrant(
        event_id=ident(event),
        cup_team_id=team_id,
        waitlisted_at=utcnow() if waits else None,
    )
    session.add(row)
    session.flush()
    return row


def _invite(
    session: OrmSession, event_id: int, team_id: int, user_id: int
) -> CupTeamInvite:
    row = session.get(CupTeamInvite, (team_id, user_id))
    if row is None or row.event_id != event_id:
        raise NotFoundError("No invite of this team for that player")
    return row


def _hold_captain(
    session: OrmSession, event_id: int, team_id: int, claims: dict[str, Any] | None
) -> None:
    caller = event_service._caller(session, claims)
    seat = (
        session.get(CupTeamMember, (team_id, ident(caller)))
        if caller is not None
        else None
    )
    team = session.get(CupTeam, team_id)
    if seat is None or not seat.captain or team is None or team.event_id != event_id:
        raise ApiError(403, {"error": "Only the captain of the team does this"})


def _roster_count(session: OrmSession, team_id: int) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(CupTeamMember)
            .where(col(CupTeamMember.team_id) == team_id)
        )
        or 0
    )


def _invite_count(session: OrmSession, team_id: int) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(CupTeamInvite)
            .where(col(CupTeamInvite.team_id) == team_id)
        )
        or 0
    )


def _entrant_of(session: OrmSession, event_id: int, team_id: int) -> EventEntrant:
    row = session.scalars(
        select(EventEntrant).where(
            col(EventEntrant.event_id) == event_id,
            col(EventEntrant.cup_team_id) == team_id,
        )
    ).first()
    if row is None:
        raise NotFoundError(f"Team not found in this event by id: {team_id}")
    return row


def _hold_unplayed(session: OrmSession, entrant: EventEntrant) -> None:
    """Refuse a change of roster once the team has played a match."""
    entrant_id = ident(entrant)
    played = session.scalars(
        select(CupSeries).where(
            or_(
                col(CupSeries.entrant1_id) == entrant_id,
                col(CupSeries.entrant2_id) == entrant_id,
            ),
            col(CupSeries.entrant1_id).is_not(None),
            col(CupSeries.entrant2_id).is_not(None),
        )
    ).all()
    if any(scored(row) for row in played):
        raise BadRequestError(
            "This team has played a match already, so its roster stays"
        )
