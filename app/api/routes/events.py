"""The event routes. Reads are open; every write asks for an admin."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import EventServiceDep, require_admin
from app.models.enums import EventKind
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
