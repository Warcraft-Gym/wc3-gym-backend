import logging
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query

from app.api.deps import SeasonServiceDep, require_admin
from app.core.exceptions import BadRequestError
from app.core.query import QueryUtil
from app.models.season import SeasonCreate, SeasonPublic, SeasonUpdate
from app.models.user import UserListPublic
from app.models.w3c_stats import W3CSyncResult

logger = logging.getLogger(__name__)

router = APIRouter(tags=["seasons"])


@router.post(
    "/seasons",
    status_code=201,
    response_model=SeasonPublic,
    dependencies=[Depends(require_admin)],
)
def add_season(data: SeasonCreate, service: SeasonServiceDep) -> SeasonPublic:
    """Create a new season with the provided name."""
    return service.add(data)


@router.put(
    "/seasons/{season_id}",
    response_model=SeasonPublic,
    dependencies=[Depends(require_admin)],
)
def update_season(
    season_id: int, data: SeasonUpdate, service: SeasonServiceDep
) -> SeasonPublic:
    """Update the name of an existing season."""
    return service.update(season_id, data)


@router.delete(
    "/seasons/{season_id}", status_code=204, dependencies=[Depends(require_admin)]
)
def delete_season(season_id: int, service: SeasonServiceDep) -> None:
    """Delete a season by its ID."""
    service.delete(season_id)


@router.get("/seasons/{season_id}")
def get_season(season_id: int, service: SeasonServiceDep) -> SeasonPublic:
    """Retrieve a season by its ID."""
    return service.get(season_id)


@router.post("/seasons/addTeams/{season_id}", dependencies=[Depends(require_admin)])
def add_teams(
    season_id: int, data: Annotated[dict, Body()], service: SeasonServiceDep
) -> SeasonPublic:
    """Add teams to season by providing a list of team ids."""
    return service.addTeams(season_id, data.get("team_ids"))


@router.post("/seasons/removeTeams/{season_id}", dependencies=[Depends(require_admin)])
def remove_teams(
    season_id: int, data: Annotated[dict, Body()], service: SeasonServiceDep
) -> SeasonPublic:
    """Remove teams from season by providing a list of team ids."""
    return service.removeTeams(season_id, data.get("team_ids"))


@router.get("/seasons")
def get_all(
    service: SeasonServiceDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SeasonPublic]:
    """Return one page of seasons, at most 500."""
    return service.getAll(limit=limit, offset=offset) or []


@router.post("/seasons/search")
def search_seasons(
    service: SeasonServiceDep,
    query: str = "",
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SeasonPublic]:
    """Search seasons by criteria using a custom query format."""
    parsed_query = QueryUtil.parseQuery(query)
    if not parsed_query or not parsed_query.elementA:
        raise BadRequestError(f"No valid query found: {query}")
    return service.search(parsed_query, limit=limit, offset=offset) or []


@router.post("/seasons/addMaps/{season_id}", dependencies=[Depends(require_admin)])
def add_maps(
    season_id: int, data: Annotated[dict, Body()], service: SeasonServiceDep
) -> SeasonPublic:
    """Add maps to season by providing a list of map ids."""
    return service.addMaps(season_id, data.get("map_ids"))


@router.post("/seasons/removeMaps/{season_id}", dependencies=[Depends(require_admin)])
def remove_maps(
    season_id: int, data: Annotated[dict, Body()], service: SeasonServiceDep
) -> SeasonPublic:
    """Remove maps from season by providing a list of map ids."""
    return service.removeMaps(season_id, data.get("map_ids"))


@router.post(
    "/seasons/addUserSignup/{season_id}", dependencies=[Depends(require_admin)]
)
def add_user_signup(
    season_id: int, data: Annotated[dict, Body()], service: SeasonServiceDep
) -> SeasonPublic:
    """Add signup users to season by providing a list of user ids."""
    return service.addUserSignup(season_id, data.get("user_ids"))


@router.post(
    "/seasons/removeUserSignup/{season_id}", dependencies=[Depends(require_admin)]
)
def remove_user_signup(
    season_id: int, data: Annotated[dict, Body()], service: SeasonServiceDep
) -> SeasonPublic:
    """Remove signup users from season by providing a list of user ids."""
    return service.removeUserSignup(season_id, data.get("user_ids"))


@router.get("/seasons/{season_id}/signups")
def get_season_signups(
    season_id: int,
    service: SeasonServiceDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[UserListPublic]:
    """Retrieve one page of the users signed up for a season, at most 500."""
    return service.getSignedUpUsers(season_id, limit=limit, offset=offset) or []


@router.post("/seasons/{season_id}/w3c_sync", dependencies=[Depends(require_admin)])
def sync_w3c_season_signups(season_id: int, service: SeasonServiceDep) -> W3CSyncResult:
    """Sync w3c information for every player signed up for the season."""
    return service.syncW3CStatsSeason(season_id)
