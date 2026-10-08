"""Who organizes events beside the admins.

An admin grants and revokes organizers, and answers the requests members
send. The runners of an event add and remove its co-organizers.
"""

from fastapi import APIRouter, Depends

from app.api.deps import (
    EventServiceDep,
    RequireAdmin,
    RequireEventRunner,
    RequireLogin,
    require_admin,
    require_event_runner,
)
from app.api.routes.public import Identity
from app.models.organizer import (
    EventOrganizerPublic,
    EventOrganizerWrite,
    OrganizerGrantCreate,
    OrganizerPublic,
    OrganizerRequestCreate,
    OrganizerRequestPublic,
)
from app.models.season import EventPublic
from app.services import organizers

router = APIRouter(tags=["organizers"])


@router.get("/organizers", dependencies=[Depends(require_admin)])
def get_organizers() -> list[OrganizerPublic]:
    """Every organizer grant, oldest first, with how many events each runs."""
    return organizers.organizers()


@router.post("/organizers", status_code=201)
def add_organizer(
    data: OrganizerGrantCreate, granted_by: RequireAdmin
) -> OrganizerPublic:
    """Make that Discord account an organizer; its open request closes."""
    return organizers.grant(data.discord_id, granted_by, data.name)


@router.delete(
    "/organizers/{discord_id}", status_code=204, dependencies=[Depends(require_admin)]
)
def delete_organizer(discord_id: str) -> None:
    """Take a grant back; the events the account runs keep it as an organizer."""
    organizers.revoke(discord_id)


@router.post("/organizers/requests", status_code=204)
def request_organizer(data: OrganizerRequestCreate, entry: Identity) -> None:
    """A member asks to become an organizer; a second ask rewrites the note."""
    organizers.request(entry["discord_id"], entry["discord_tag"], data.note)


@router.get("/organizers/requests", dependencies=[Depends(require_admin)])
def get_organizer_requests() -> list[OrganizerRequestPublic]:
    """Every open request, oldest first."""
    return organizers.requests()


@router.post("/organizers/requests/{discord_id}/approve", status_code=201)
def approve_organizer(discord_id: str, granted_by: RequireAdmin) -> OrganizerPublic:
    """Grant what the request asked for."""
    return organizers.grant(discord_id, granted_by)


@router.post(
    "/organizers/requests/{discord_id}/decline",
    status_code=204,
    dependencies=[Depends(require_admin)],
)
def decline_organizer(discord_id: str) -> None:
    """Close the request without a grant."""
    organizers.decline(discord_id)


@router.get("/me/organized-events", tags=["events"])
def get_my_organized_events(
    claims: RequireLogin, service: EventServiceDep
) -> list[EventPublic]:
    """The events the caller runs, newest first, drafts included. A guest, the
    admin token and an admin viewing as a lower role run none of them."""
    if claims.get("role") == "guest" or "actual_role" in claims:
        return []
    return service.by_ids(organizers.organized_event_ids(str(claims["sub"])))


@router.get("/events/{event_id}/organizers", tags=["events"])
def get_event_organizers(event_id: int) -> list[EventOrganizerPublic]:
    """Who runs the event, in the order they were added."""
    return organizers.event_organizers(event_id)


@router.post("/events/{event_id}/organizers", status_code=201, tags=["events"])
def add_event_organizer(
    event_id: int, data: EventOrganizerWrite, claims: RequireEventRunner
) -> list[EventOrganizerPublic]:
    """Let one more account run the event."""
    return organizers.add_to_event(event_id, data.discord_id, claims["sub"], data.name)


@router.delete(
    "/events/{event_id}/organizers/{discord_id}",
    status_code=204,
    tags=["events"],
    dependencies=[Depends(require_event_runner)],
)
def delete_event_organizer(event_id: int, discord_id: str) -> None:
    """Stop an account running the event."""
    organizers.remove_from_event(event_id, discord_id)
