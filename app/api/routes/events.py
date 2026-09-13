"""The event routes. Reads are open; every write asks for an admin."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import (
    EventServiceDep,
    OptionalLogin,
    RequireLogin,
    require_admin,
)
from app.models.enums import EventKind
from app.models.event_entrant import (
    EntrantAdd,
    EntrantSignup,
    EventEntrantPublic,
)
from app.models.event_stage import EventStageWrite
from app.models.season import EventCreate, EventPublic, EventUpdate

router = APIRouter(tags=["events"])


@router.get("/events")
def get_events(
    service: EventServiceDep,
    kind: EventKind | None = None,
    league_id: int | None = None,
    published: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[EventPublic]:
    """Return one page of events, at most 500, each with its computed phase."""
    return service.get_all(
        kind=kind, league_id=league_id, published=published, limit=limit, offset=offset
    )


@router.get("/events/{event_id}")
def get_event(event_id: int, service: EventServiceDep) -> EventPublic:
    """Return one event with its stages, its divisions and its entrant count."""
    return service.get(event_id)


@router.post("/events", status_code=201, dependencies=[Depends(require_admin)])
def add_event(data: EventCreate, service: EventServiceDep) -> EventPublic:
    """Create an event with the stages the body names, or one default stage."""
    return service.add(data)


@router.put("/events/{event_id}", dependencies=[Depends(require_admin)])
def update_event(
    event_id: int, data: EventUpdate, service: EventServiceDep
) -> EventPublic:
    """Change the event fields the body names."""
    return service.update(event_id, data)


@router.put("/events/{event_id}/stages", dependencies=[Depends(require_admin)])
def set_stages(
    event_id: int, stages: list[EventStageWrite], service: EventServiceDep
) -> EventPublic:
    """Replace the stage list; the order of the body is the order they play in."""
    return service.set_stages(event_id, stages)


@router.get("/events/{event_id}/entrants")
def get_entrants(event_id: int, service: EventServiceDep) -> list[EventEntrantPublic]:
    """Every entrant of the event, with its rating on the signup race and warnings."""
    return service.get_entrants(event_id)


@router.post("/events/{event_id}/entrants", status_code=201)
def add_entrant(
    event_id: int,
    data: EntrantSignup,
    claims: OptionalLogin,
    service: EventServiceDep,
) -> EventEntrantPublic:
    """Sign the caller up, or the team the caller captains."""
    return service.add_entrant(event_id, data, claims)


@router.post(
    "/events/{event_id}/entrants/admin",
    status_code=201,
    dependencies=[Depends(require_admin)],
)
def add_entrant_as_admin(
    event_id: int, data: EntrantAdd, service: EventServiceDep
) -> EventEntrantPublic:
    """Enter any player or team, whether signups stand open or not."""
    return service.add_entrant_as_admin(event_id, data)


@router.delete("/events/{event_id}/entrants/me", status_code=204)
def withdraw(event_id: int, claims: RequireLogin, service: EventServiceDep) -> None:
    """Withdraw the caller's own signup; the row stays and reads withdrawn."""
    service.withdraw(event_id, claims)


@router.post("/events/{event_id}/entrants/{entrant_id}/checkin")
def check_in(
    event_id: int,
    entrant_id: int,
    claims: RequireLogin,
    service: EventServiceDep,
) -> EventEntrantPublic:
    """Check one entrant in: the caller's own row, or any row for an admin."""
    return service.check_in(event_id, entrant_id, claims)


@router.delete(
    "/events/{event_id}/entrants/{entrant_id}",
    status_code=204,
    dependencies=[Depends(require_admin)],
)
def remove_entrant(event_id: int, entrant_id: int, service: EventServiceDep) -> None:
    """Remove one entrant row."""
    service.remove_entrant(event_id, entrant_id)
