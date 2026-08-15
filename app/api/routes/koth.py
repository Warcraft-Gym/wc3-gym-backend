import logging
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from app.api.deps import KothServiceDep, require_admin
from app.models.koth_event import KothEventCreate, KothEventPublic, KothEventUpdate
from app.models.koth_match import (
    KothMatchCreate,
    KothMatchCreateRequest,
    KothMatchPublic,
    KothMatchUpdate,
)
from app.models.koth_signup import KothSignupPublic

logger = logging.getLogger(__name__)

router = APIRouter(tags=["koth"])


# ============ Event Endpoints ============
@router.get("/koth/events")
def get_all_events(service: KothServiceDep) -> list[KothEventPublic]:
    """Retrieve all King of the Hill events."""
    return service.get_all_events()


@router.get("/koth/events/active")
def get_active_event(service: KothServiceDep) -> KothEventPublic:
    """Retrieve the currently active King of the Hill event with all signups and matches."""
    return service.get_active_event()


@router.get("/koth/events/{event_id}")
def get_event(event_id: int, service: KothServiceDep) -> KothEventPublic:
    """Retrieve a specific King of the Hill event with all signups and matches."""
    return service.get_event(event_id)


@router.post(
    "/koth/events",
    status_code=201,
    response_model=KothEventPublic,
    dependencies=[Depends(require_admin)],
)
def create_event(data: KothEventCreate, service: KothServiceDep) -> KothEventPublic:
    """Create a new King of the Hill event."""
    return service.create_event(data)


@router.put(
    "/koth/events/{event_id}",
    response_model=KothEventPublic,
    dependencies=[Depends(require_admin)],
)
def update_event(
    event_id: int, data: KothEventUpdate, service: KothServiceDep
) -> KothEventPublic:
    """Update an existing King of the Hill event."""
    return service.update_event(event_id, data)


@router.post("/koth/events/{event_id}/activate", dependencies=[Depends(require_admin)])
def activate_event(event_id: int, service: KothServiceDep) -> KothEventPublic:
    """Set a KOTH event as active and deactivate all others."""
    return service.set_active_event(event_id)


@router.delete(
    "/koth/events/{event_id}", status_code=204, dependencies=[Depends(require_admin)]
)
def delete_event(event_id: int, service: KothServiceDep) -> None:
    """Delete a King of the Hill event and all associated signups and matches."""
    service.delete_event(event_id)


# ============ Signup Endpoints ============
@router.get("/koth/events/{event_id}/signups")
def get_event_signups(event_id: int, service: KothServiceDep) -> list[KothSignupPublic]:
    """Retrieve all signups for a specific KOTH event."""
    return service.get_signups_by_event(event_id)


@router.post("/koth/signups", status_code=201, response_model=None)
def create_signup(
    data: Annotated[dict, Body()], service: KothServiceDep
) -> JSONResponse | dict[str, Any] | None:
    """Create a signup (Twitch/Nightbot endpoint).

    Create a KOTH signup with automatic W3C MMR validation and bracket
    assignment. Requires KOTH_NIGHTBOT_TOKEN for authentication.
    """
    try:
        # Verify KOTH_NIGHTBOT_TOKEN from settings
        client_token = data.get("client_token")
        setting = service.settings_app_service.get_setting("KOTH_NIGHTBOT_TOKEN")
        expected = setting.get("value") if setting else None

        if not expected or str(client_token) != str(expected):
            return JSONResponse(
                {"error": "Unauthorized - invalid client token"}, status_code=401
            )

        twitch_username = data.get("twitch_username")
        battle_tag = data.get("battle_tag")
        race = data.get("race")  # Optional

        if not twitch_username or not battle_tag:
            return JSONResponse({"error": "Missing required fields"}, status_code=400)

        signup = service.create_signup_from_twitch(
            twitch_username=twitch_username, battle_tag=battle_tag, preferred_race=race
        )
        return signup.to_dict()
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.get("/koth/signup", response_model=None)
def create_signup_nightbot(
    service: KothServiceDep,
    token: str | None = None,
    twitch: str | None = None,
    battletag: str | None = None,
    race: str | None = None,
) -> JSONResponse | dict[str, Any] | None:
    """Create a signup via URL parameters (Nightbot compatible).

    Create a KOTH signup using query parameters. Compatible with Nightbot
    and other chat bots that cannot send JSON body. Requires
    KOTH_NIGHTBOT_TOKEN for authentication.
    Usage: GET /koth/signup?token=KOTH_TOKEN&twitch=username&battletag=Name%231234
    """
    try:
        client_token = token
        twitch_username = twitch
        battle_tag = battletag

        # Verify KOTH_NIGHTBOT_TOKEN from settings
        setting = service.settings_app_service.get_setting("KOTH_NIGHTBOT_TOKEN")
        expected = setting.get("value") if setting else None

        if not expected or str(client_token) != str(expected):
            return JSONResponse(
                {"error": "Unauthorized - invalid client token"}, status_code=401
            )

        if not twitch_username or not battle_tag:
            return JSONResponse(
                {"error": "Missing required parameters: token, twitch, battletag"},
                status_code=400,
            )

        signup = service.create_signup_from_twitch(
            twitch_username=twitch_username, battle_tag=battle_tag, preferred_race=race
        )

        # Return simple success message for chat display
        return {
            "success": True,
            "message": f"{twitch_username} signed up for Bracket {signup.bracket} ({signup.mmr} MMR)",
        }
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.post(
    "/koth/signups/admin",
    status_code=201,
    dependencies=[Depends(require_admin)],
    response_model=None,
)
def create_signup_admin(
    data: Annotated[dict, Body()], service: KothServiceDep
) -> JSONResponse | dict[str, Any] | None:
    """Create a signup manually (Admin).

    Manually create a KOTH signup with automatic W3C MMR validation and
    bracket assignment. For admin UI use.
    """
    try:
        twitch_username = data.get("twitch_username", "")
        battle_tag = data.get("battle_tag")
        race = data.get("race")

        if not battle_tag:
            return JSONResponse({"error": "BattleTag is required"}, status_code=400)

        signup = service.create_signup_from_twitch(
            twitch_username=twitch_username, battle_tag=battle_tag, preferred_race=race
        )
        return signup.to_dict()
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.put(
    "/koth/signups/{signup_id}/bracket",
    dependencies=[Depends(require_admin)],
    response_model=None,
)
def update_signup_bracket(
    signup_id: int, data: Annotated[dict, Body()], service: KothServiceDep
) -> JSONResponse | dict[str, Any] | None:
    """Manually update a player's bracket assignment."""
    try:
        return service.update_signup_bracket(signup_id, data.get("bracket")).to_dict()
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.post("/koth/signups/{signup_id}/king", dependencies=[Depends(require_admin)])
def set_king(signup_id: int, service: KothServiceDep) -> KothSignupPublic:
    """Set a player as the king of their bracket (overwrites existing kings)."""
    return service.set_king(signup_id)


@router.post(
    "/koth/signups/{signup_id}/add-king", dependencies=[Depends(require_admin)]
)
def add_king(signup_id: int, service: KothServiceDep) -> KothSignupPublic:
    """Add a player as king of their bracket (keeps existing kings)."""
    return service.add_king(signup_id)


@router.delete("/koth/signups/{signup_id}/king", dependencies=[Depends(require_admin)])
def unset_king(signup_id: int, service: KothServiceDep) -> KothSignupPublic:
    """Remove king status from a player."""
    return service.unset_king(signup_id)


@router.delete(
    "/koth/signups/{signup_id}", status_code=204, dependencies=[Depends(require_admin)]
)
def delete_signup(signup_id: int, service: KothServiceDep) -> None:
    """Remove a player signup from an event."""
    service.delete_signup(signup_id)


# ============ Match Endpoints ============
@router.get("/koth/events/{event_id}/matches")
def get_event_matches(event_id: int, service: KothServiceDep) -> list[KothMatchPublic]:
    """Retrieve all matches for a specific KOTH event."""
    return service.get_matches_by_event(event_id)


@router.post(
    "/koth/matches",
    status_code=201,
    response_model=KothMatchPublic,
    dependencies=[Depends(require_admin)],
)
def create_match(
    data: KothMatchCreateRequest, service: KothServiceDep
) -> JSONResponse | KothMatchPublic | None:
    """Create a team-based match.

    Create a new KOTH match with flexible team configuration. Supports
    uneven teams (e.g., 2v1, 3v1).
    """
    try:
        participants = [p.model_dump() for p in data.participants]
        match = KothMatchCreate.model_validate(data, from_attributes=True)
        return service.create_match(match, participants)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.put(
    "/koth/matches/{match_id}",
    response_model=KothMatchPublic,
    dependencies=[Depends(require_admin)],
)
def update_match(
    match_id: int, data: KothMatchUpdate, service: KothServiceDep
) -> KothMatchPublic:
    """Update a KOTH match."""
    return service.update_match(match_id, data)


@router.put("/koth/matches/{match_id}/result", dependencies=[Depends(require_admin)])
def update_match_result(
    match_id: int, data: Annotated[dict, Body()], service: KothServiceDep
) -> KothMatchPublic:
    """Set the winning team and update all team members as kings."""
    return service.update_match_result(match_id, data.get("winner_team_number"))


@router.delete(
    "/koth/matches/{match_id}", status_code=204, dependencies=[Depends(require_admin)]
)
def delete_match(match_id: int, service: KothServiceDep) -> None:
    """Remove a match from an event."""
    service.delete_match(match_id)


# ============ Utility Endpoints ============
@router.get("/koth/events/{event_id}/kings")
def get_bracket_kings(
    event_id: int, service: KothServiceDep
) -> dict[int, list[KothSignupPublic]]:
    """Get all kings for each bracket in an event."""
    return service.get_bracket_kings(event_id)
