"""The league routes. A league is the thing that repeats; its runs are events."""

from fastapi import APIRouter, Depends

from app.api.deps import EventServiceDep, OptionalLogin, require_admin
from app.models.league import LeagueCreate, LeaguePublic, LeagueUpdate

router = APIRouter(tags=["leagues"])


@router.get("/leagues")
def get_leagues(service: EventServiceDep) -> list[LeaguePublic]:
    """Return every league, without its events."""
    return service.get_leagues()


@router.get("/leagues/{league_id}")
def get_league(
    league_id: int, service: EventServiceDep, claims: OptionalLogin
) -> LeaguePublic:
    """Return one league and the events that are its runs, newest first.

    A draft run is in the list for an admin only.
    """
    return service.get_league(league_id, claims=claims)


@router.post("/leagues", status_code=201, dependencies=[Depends(require_admin)])
def add_league(data: LeagueCreate, service: EventServiceDep) -> LeaguePublic:
    """Create a league."""
    return service.add_league(data)


@router.put("/leagues/{league_id}", dependencies=[Depends(require_admin)])
def update_league(
    league_id: int, data: LeagueUpdate, service: EventServiceDep
) -> LeaguePublic:
    """Change the league fields the body names."""
    return service.update_league(league_id, data)
