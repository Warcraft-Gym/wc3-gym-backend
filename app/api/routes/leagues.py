"""The public league reads. A league is the thing that repeats; its runs are events."""

from fastapi import APIRouter

from app.api.deps import EventServiceDep
from app.models.league import LeaguePublic

router = APIRouter(tags=["leagues"])


@router.get("/leagues")
def get_leagues(service: EventServiceDep) -> list[LeaguePublic]:
    """Return every league, without its events."""
    return service.get_leagues()


@router.get("/leagues/{league_id}")
def get_league(league_id: int, service: EventServiceDep) -> LeaguePublic:
    """Return one league and the events that are its runs, newest first."""
    return service.get_league(league_id)
