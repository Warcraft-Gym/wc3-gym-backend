"""The old KOTH paths, answered from the event model by the KOTH module.

Every handler here keeps the path, the body and the payload it answered
before, so Nightbot, the overlay and the bookmarks of the run crew keep
working while the pages move to the event reads. 4f drops these paths.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import RequireLogin, UserServiceDep, require_admin
from app.core.exceptions import BadRequestError
from app.models.enums import SignupChannel
from app.models.koth_legacy import (
    KothBracketUpdate,
    KothEventCreate,
    KothEventPublic,
    KothEventSummary,
    KothEventUpdate,
    KothMatchCreate,
    KothMatchCreateRequest,
    KothMatchPublic,
    KothMatchResult,
    KothMatchUpdate,
    KothSignupAdminRequest,
    KothSignupMeRequest,
    KothSignupPublic,
    KothSignupRequest,
)
from app.services.koth import legacy

logger = logging.getLogger(__name__)

router = APIRouter(tags=["koth"])


# ============ Event Endpoints ============
@router.get("/koth/events")
def get_all_events() -> list[KothEventSummary]:
    """Retrieve all King of the Hill events, without their signups and matches."""
    return legacy.all_events()


@router.get("/koth/events/active")
def get_active_event() -> KothEventPublic:
    """Retrieve the currently active King of the Hill event with all signups and matches."""
    return legacy.active_event()


@router.get("/koth/events/{event_id}")
def get_event(event_id: int) -> KothEventPublic:
    """Retrieve a specific King of the Hill event with all signups and matches."""
    return legacy.event(event_id)


@router.post(
    "/koth/events",
    status_code=201,
    response_model=KothEventPublic,
    dependencies=[Depends(require_admin)],
)
def create_event(data: KothEventCreate) -> KothEventPublic:
    """Open a King of the Hill night from the old create body."""
    return legacy.add_event(data)


@router.put(
    "/koth/events/{event_id}",
    response_model=KothEventPublic,
    dependencies=[Depends(require_admin)],
)
def update_event(event_id: int, data: KothEventUpdate) -> KothEventPublic:
    """Update an existing King of the Hill event."""
    return legacy.update_event(event_id, data)


@router.post("/koth/events/{event_id}/activate", dependencies=[Depends(require_admin)])
def activate_event(event_id: int) -> KothEventPublic:
    """Open this night for signups and close every other one."""
    return legacy.activate_event(event_id)


@router.delete(
    "/koth/events/{event_id}", status_code=204, dependencies=[Depends(require_admin)]
)
def delete_event(event_id: int) -> None:
    """Delete a King of the Hill event and everything played in it."""
    legacy.delete_event(event_id)


# ============ Signup Endpoints ============
@router.get("/koth/events/{event_id}/signups")
def get_event_signups(
    event_id: int,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[KothSignupPublic]:
    """Retrieve one page of the signups of a KOTH event, at most 500."""
    return legacy.signups_of(event_id, limit=limit, offset=offset)


@router.post("/koth/signups", status_code=201)
def create_signup(data: KothSignupRequest) -> KothSignupPublic:
    """Create a signup with automatic W3C MMR validation and bracket assignment.

    Open by decision: Twitch chat signups are permissionless anyway, and the
    token this route used to require was readable by any visitor. A sent
    client_token is accepted and ignored, so Nightbot keeps working.
    """
    if not data.twitch_username or not data.battle_tag:
        raise BadRequestError("Missing required fields")
    signups = legacy.create_signups(
        battle_tag=data.battle_tag, races=[data.race] if data.race else None
    )
    return signups[0]


@router.post(
    "/koth/signups/admin",
    status_code=201,
    dependencies=[Depends(require_admin)],
)
def create_signup_admin(data: KothSignupAdminRequest) -> list[KothSignupPublic]:
    """Create a signup manually (Admin).

    A night holds one entrant per player, so a body naming several races
    writes the last of them. The signup lands on the event the admin is
    looking at, or on the night that takes signups.
    """
    return legacy.create_signups(
        battle_tag=data.battle_tag,
        races=data.races,
        event_id=data.event_id,
        channel=SignupChannel.web,
    )


@router.post("/koth/signups/me", status_code=201)
def create_signup_me(
    data: KothSignupMeRequest,
    claims: RequireLogin,
    user_service: UserServiceDep,
) -> list[KothSignupPublic]:
    """Sign the logged-in player up for the night that takes signups.

    The battle tag comes from the player's profile, so the player names only
    the race they want to play.
    """
    users = user_service.find_by_discord_id(claims["sub"])
    if not users or not users[0].battleTag:
        raise BadRequestError("Your profile carries no battle tag")
    return legacy.create_signups(
        battle_tag=users[0].battleTag, races=data.races, channel=SignupChannel.web
    )


@router.delete("/koth/signups/me", status_code=204)
def delete_signup_me(
    claims: RequireLogin,
    user_service: UserServiceDep,
    race: str | None = None,
) -> None:
    """Withdraw the logged-in player's signup from the night that takes signups."""
    users = user_service.find_by_discord_id(claims["sub"])
    if not users or not users[0].battleTag:
        raise BadRequestError("Your profile carries no battle tag")
    legacy.withdraw(users[0].battleTag, race)


@router.put(
    "/koth/signups/{signup_id}/bracket",
    dependencies=[Depends(require_admin)],
)
def update_signup_bracket(signup_id: int, data: KothBracketUpdate) -> KothSignupPublic:
    """Manually update a player's bracket assignment."""
    return legacy.set_bracket(signup_id, data.bracket)


@router.post("/koth/signups/{signup_id}/king", dependencies=[Depends(require_admin)])
def set_king(signup_id: int) -> KothSignupPublic:
    """Put a player on the throne seat of his chain, while it is unplayed."""
    return legacy.crown(signup_id)


@router.post(
    "/koth/signups/{signup_id}/add-king", dependencies=[Depends(require_admin)]
)
def add_king(signup_id: int) -> KothSignupPublic:
    """A bracket holds one king, so this path answers 400."""
    raise BadRequestError(legacy.NO_MANUAL_KING)


@router.delete("/koth/signups/{signup_id}/king", dependencies=[Depends(require_admin)])
def unset_king(signup_id: int) -> KothSignupPublic:
    """The crown is not stored, so it cannot be taken; this path answers 400."""
    raise BadRequestError(legacy.NO_MANUAL_KING)


@router.delete(
    "/koth/signups/{signup_id}", status_code=204, dependencies=[Depends(require_admin)]
)
def delete_signup(signup_id: int) -> None:
    """Remove a player signup from an event."""
    legacy.delete_signup(signup_id)


# ============ Match Endpoints ============
@router.get("/koth/events/{event_id}/matches")
def get_event_matches(
    event_id: int,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[KothMatchPublic]:
    """Retrieve one page of the matches of a KOTH event, at most 500."""
    return legacy.matches_of(event_id, limit=limit, offset=offset)


@router.post(
    "/koth/matches",
    status_code=201,
    dependencies=[Depends(require_admin)],
)
def create_match(data: KothMatchCreateRequest) -> KothMatchPublic:
    """Create one series of a chain from the old team-based body.

    A KOTH series is one player against one player, so a body that names
    more than one player a side answers 400.
    """
    participants = [p.model_dump() for p in data.participants]
    match = KothMatchCreate.model_validate(data, from_attributes=True)
    return legacy.create_match(match, participants)


@router.put(
    "/koth/matches/{match_id}",
    response_model=KothMatchPublic,
    dependencies=[Depends(require_admin)],
)
def update_match(match_id: int, data: KothMatchUpdate) -> KothMatchPublic:
    """Update a KOTH match."""
    return legacy.update_match(match_id, data)


@router.put("/koth/matches/{match_id}/result", dependencies=[Depends(require_admin)])
def update_match_result(match_id: int, data: KothMatchResult) -> KothMatchPublic:
    """Score the series; its winner holds the throne of the chain."""
    return legacy.match_result(match_id, data.winner_team_number)


@router.delete(
    "/koth/matches/{match_id}", status_code=204, dependencies=[Depends(require_admin)]
)
def delete_match(match_id: int) -> None:
    """Remove a match from an event."""
    legacy.delete_match(match_id)


# ============ Utility Endpoints ============
@router.get("/koth/events/{event_id}/kings")
def get_bracket_kings(event_id: int) -> dict[int, list[KothSignupPublic]]:
    """Get the king of each bracket in an event."""
    return legacy.kings_of(event_id)
