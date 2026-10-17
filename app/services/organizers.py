"""Who organizes events beside the admins, and which events each one runs.

An organizer is a Discord account with a grant, as an admin is, so it needs no
player row. The grant counts only while the account is a member of the guild,
so a guest or an admin viewing as a lower role holds none. A grant lets the
account create events; a row of event_organizer lets an account run that one
event, and outlives the grant. An admin runs every event.
"""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, case, exists, func, or_, select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core.db import Session
from app.core.exceptions import ApiError, BadRequestError, NotFoundError
from app.core.security import is_admin
from app.models.base import ident
from app.models.enums import EventKind, LeagueKind, StageFormat
from app.models.league import League
from app.models.organizer import (
    EventOrganizer,
    EventOrganizerPublic,
    OrganizerCandidate,
    OrganizerGrant,
    OrganizerPublic,
    OrganizerRequest,
    OrganizerRequestPublic,
)
from app.models.season import Season
from app.models.user import User

ALREADY = "Already an organizer"


def _member(claims: dict[str, Any] | None) -> bool:
    """A guild member acting as itself: no guest, no admin seen as a lower role."""
    return (
        claims is not None
        and claims.get("role") in ("member", "captain")
        and "actual_role" not in claims
    )


def standing(claims: dict[str, Any] | None) -> tuple[bool, bool]:
    """Whether the account holds a grant, and whether it has a request open, in
    one statement. A grant counts only for a member acting as itself."""
    if claims is None or claims.get("sub") == "admin":
        return False, False
    discord_id = str(claims["sub"])
    with Session.begin() as session:
        granted, requested = session.execute(
            select(
                exists().where(col(OrganizerGrant.discord_id) == discord_id),
                exists().where(col(OrganizerRequest.discord_id) == discord_id),
            )
        ).one()
    return bool(granted) and _member(claims), bool(requested)


def is_organizer(claims: dict[str, Any] | None) -> bool:
    """Whether the caller may create events: an admin, or a member with a grant."""
    return is_admin(claims) or standing(claims)[0]


def is_organizer_in(session: OrmSession, claims: dict[str, Any] | None) -> bool:
    """`is_organizer`, inside the caller's session: an admin reads nothing."""
    if is_admin(claims):
        return True
    if not _member(claims):
        return False
    discord_id = str(claims["sub"])
    return bool(
        session.scalar(
            select(exists().where(col(OrganizerGrant.discord_id) == discord_id))
        )
    )


def runs(claims: dict[str, Any] | None, event_id: int) -> bool:
    """Whether the caller runs that event: an admin, or a member holding its row."""
    with Session.begin() as session:
        return runs_in(session, claims, event_id)


def runs_in(session: OrmSession, claims: dict[str, Any] | None, event_id: int) -> bool:
    """`runs`, inside the caller's session: an admin reads nothing."""
    if is_admin(claims):
        return True
    if not _member(claims):
        return False
    return session.get(EventOrganizer, (event_id, str(claims["sub"]))) is not None


def shows_seeds(claims: dict[str, Any] | None, event: Season) -> bool:
    """Whether the caller reads the event's seed numbers: always, unless the
    event hides them, and then only for a caller who runs it."""
    return not event.hide_seeds or runs(claims, ident(event))


def _player_name(session: OrmSession, discord_id: str) -> str:
    """The name to show for an account: its player row's, else its grant's."""
    return (
        session.scalar(select(col(User.name)).where(col(User.discordId) == discord_id))
        or session.scalar(
            select(col(OrganizerGrant.name)).where(
                col(OrganizerGrant.discord_id) == discord_id
            )
        )
        or ""
    )


# The kinds and the formats an organizer writes; the GNL and KOTH stay the admins'
ORGANIZER_KINDS = {EventKind.cup, EventKind.signup}
ADMIN_FORMATS = {StageFormat.gnl, StageFormat.koth}


def hold_to_small_events(
    claims: dict[str, Any],
    fields: dict[str, Any],
    formats: Sequence[StageFormat] = (),
) -> None:
    """Refuse an organizer's event write that reaches past a small event.

    An organizer writes an event of no league or of a custom league, of a
    small kind, with no GNL Discord role and no admin format, under a parent
    it runs itself. An admin passes untouched.
    """
    if is_admin(claims):
        return

    def refuse(why: str) -> None:
        raise ApiError(403, {"error": why})

    if "kind" in fields and fields["kind"] not in ORGANIZER_KINDS:
        refuse("Organizers create cups and sign-up lists")
    if fields.get("discordRole"):
        refuse("The Discord role of an event is the admins'")
    if any(one in ADMIN_FORMATS for one in formats):
        refuse("GNL and KOTH stages are the admins'")
    league_id = fields.get("league_id")
    if league_id is not None:
        with Session.begin() as session:
            league = session.get(League, league_id)
            if league is None or league.kind is not LeagueKind.custom:
                refuse("Organizers create events of their own leagues only")
    parent_id = fields.get("parent_id")
    if parent_id is not None and not runs(claims, parent_id):
        refuse("An event can only feed an event you run")


# --- grants ---


def organizers() -> list[OrganizerPublic]:
    """Every grant in the order it was made, with how many events each account runs."""
    with Session.begin() as session:
        counts: dict[str, int] = {
            discord_id: count
            for discord_id, count in session.execute(
                select(col(EventOrganizer.discord_id), func.count()).group_by(
                    col(EventOrganizer.discord_id)
                )
            )
        }
        rows = session.scalars(
            select(OrganizerGrant).order_by(col(OrganizerGrant.granted_at))
        ).all()
        return [
            OrganizerPublic(**row.model_dump(), events=counts.get(row.discord_id, 0))
            for row in rows
        ]


def grant(discord_id: str, granted_by: str, name: str = "") -> OrganizerPublic:
    """Make that account an organizer and close its request. A second grant
    changes nothing."""
    with Session.begin() as session:
        row = session.get(OrganizerGrant, discord_id)
        if row is None:
            row = OrganizerGrant(
                discord_id=discord_id,
                name=name or _player_name(session, discord_id),
                granted_by=granted_by,
            )
            session.add(row)
        request = session.get(OrganizerRequest, discord_id)
        if request is not None:
            if not row.name:
                row.name = request.name
            session.delete(request)
        session.flush()
        return OrganizerPublic(**row.model_dump())


def revoke(discord_id: str) -> None:
    """Take a grant back. The events the account runs keep its row."""
    with Session.begin() as session:
        row = session.get(OrganizerGrant, discord_id)
        if row is None:
            raise NotFoundError(f"Organizer not found by Discord id: {discord_id}")
        session.delete(row)


# --- requests ---


def request(discord_id: str, name: str, note: str | None) -> None:
    """Ask for a grant. A second request rewrites the open one."""
    with Session.begin() as session:
        if session.get(OrganizerGrant, discord_id) is not None:
            raise BadRequestError(ALREADY)
        row = session.get(OrganizerRequest, discord_id)
        if row is None:
            session.add(
                OrganizerRequest(
                    discord_id=discord_id,
                    name=name or _player_name(session, discord_id),
                    note=note,
                )
            )
        else:
            row.note = note


def requests() -> list[OrganizerRequestPublic]:
    """Every open request, oldest first, with the player row behind it if any."""
    with Session.begin() as session:
        rows = session.execute(
            select(OrganizerRequest, col(User.id))
            .outerjoin(User, col(User.discordId) == col(OrganizerRequest.discord_id))
            .order_by(col(OrganizerRequest.requested_at))
        ).all()
        return [
            OrganizerRequestPublic(**row.model_dump(), user_id=user_id)
            for row, user_id in rows
        ]


def decline(discord_id: str) -> None:
    """Close a request without a grant."""
    with Session.begin() as session:
        row = session.get(OrganizerRequest, discord_id)
        if row is None:
            raise NotFoundError(f"No open request by Discord id: {discord_id}")
        session.delete(row)


# --- the organizers of one event ---


def event_organizers(event_id: int) -> list[EventOrganizerPublic]:
    with Session.begin() as session:
        rows = session.scalars(
            select(EventOrganizer)
            .where(col(EventOrganizer.event_id) == event_id)
            .order_by(col(EventOrganizer.added_at))
        ).all()
        return [EventOrganizerPublic.model_validate(row) for row in rows]


def add_to_event(
    event_id: int, discord_id: str, added_by: str, name: str = ""
) -> list[EventOrganizerPublic]:
    """Let that account run the event. A second add changes nothing."""
    with Session.begin() as session:
        if session.get(EventOrganizer, (event_id, discord_id)) is None:
            session.add(
                EventOrganizer(
                    event_id=event_id,
                    discord_id=discord_id,
                    name=name or _player_name(session, discord_id),
                    added_by=added_by,
                )
            )
    return event_organizers(event_id)


def remove_from_event(event_id: int, discord_id: str) -> None:
    with Session.begin() as session:
        row = session.get(EventOrganizer, (event_id, discord_id))
        if row is None:
            raise NotFoundError(f"Organizer not found by Discord id: {discord_id}")
        session.delete(row)


def organized_event_ids(discord_id: str) -> list[int]:
    """The events that account runs, newest first."""
    with Session.begin() as session:
        return list(
            session.scalars(
                select(col(EventOrganizer.event_id))
                .where(col(EventOrganizer.discord_id) == discord_id)
                .order_by(col(EventOrganizer.event_id).desc())
            )
        )


# --- the players offered when an organizer is added ---

# A search answers this many players at most; the picker shows them as one short list
CANDIDATES = 10


def _candidates(text: str, taken: Select[Any]) -> list[OrganizerCandidate]:
    """The players with a Discord login whose name or Discord tag holds the text,
    in any case, past the accounts `taken` names, in one statement. A name or a
    tag that starts with the text comes first. A banned player is not offered."""
    needle = text.strip().lower()
    if len(needle) < 2:
        return []
    discord_id = func.trim(col(User.discordId))
    name = func.lower(col(User.name))
    tag = func.lower(func.coalesce(col(User.discordTag), ""))
    starts = or_(
        name.startswith(needle, autoescape=True),
        tag.startswith(needle, autoescape=True),
    )
    stmt = (
        select(col(User.id), col(User.name), col(User.discordTag), discord_id)
        .where(
            col(User.discordId).is_not(None),
            discord_id != "",
            col(User.banned_at).is_(None),
            or_(
                name.contains(needle, autoescape=True),
                tag.contains(needle, autoescape=True),
            ),
            discord_id.not_in(taken),
        )
        .order_by(case((starts, 0), else_=1), name, col(User.id))
        .limit(CANDIDATES)
    )
    with Session.begin() as session:
        return [
            OrganizerCandidate(
                user_id=user_id,
                name=user_name,
                discord_tag=user_tag,
                discord_id=account,
            )
            for user_id, user_name, user_tag, account in session.execute(stmt)
        ]


def event_candidates(event_id: int, text: str) -> list[OrganizerCandidate]:
    """The players a runner may add to that event, past the ones running it."""
    taken = select(col(EventOrganizer.discord_id)).where(
        col(EventOrganizer.event_id) == event_id
    )
    return _candidates(text, taken)


def grant_candidates(text: str) -> list[OrganizerCandidate]:
    """The players an admin may make organizers, past the ones holding a grant."""
    return _candidates(text, select(col(OrganizerGrant.discord_id)))
