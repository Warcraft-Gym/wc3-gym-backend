"""The public event reads. Writes arrive with the admin routes of a later slice."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import EventServiceDep
from app.models.season import EventPublic

router = APIRouter(tags=["events"])


@router.get("/events")
def get_events(
    service: EventServiceDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[EventPublic]:
    """Return one page of events, at most 500, each with its computed phase."""
    return service.get_all(limit=limit, offset=offset)


@router.get("/events/{event_id}")
def get_event(event_id: int, service: EventServiceDep) -> EventPublic:
    """Return one event with its stages, its divisions and its entrant count."""
    return service.get(event_id)
