import logging
from typing import Annotated

from fastapi import APIRouter, Body, Depends

from app.api.deps import SeasonServiceDep, require_admin
from app.models.season import SeasonCreate, SeasonPublic, SeasonUpdate
from app.utils.query_util import QueryUtil

logger = logging.getLogger(__name__)

router = APIRouter(tags=["seasons"])


@router.post(
    "/seasons",
    status_code=201,
    response_model=SeasonPublic,
    dependencies=[Depends(require_admin)],
)
def add_season(data: SeasonCreate, service: SeasonServiceDep):
    """Create a new season with the provided name."""
    return service.create_season(data)


@router.put(
    "/seasons/{season_id}",
    response_model=SeasonPublic,
    dependencies=[Depends(require_admin)],
)
def update_season(season_id: int, data: SeasonUpdate, service: SeasonServiceDep):
    """Update the name of an existing season."""
    return service.update_season(season_id, data)


@router.delete(
    "/seasons/{season_id}", status_code=204, dependencies=[Depends(require_admin)]
)
def delete_season(season_id: int, service: SeasonServiceDep):
    """Delete a season by its ID."""
    service.delete_season(season_id)


@router.get("/seasons/{season_id}")
def get_season(season_id: int, service: SeasonServiceDep):
    """Retrieve a season by its ID."""
    season = service.get_season(season_id)
    return season.to_dict() if season else None


@router.post("/seasons/addTeams/{season_id}", dependencies=[Depends(require_admin)])
def add_teams(season_id: int, data: Annotated[dict, Body()], service: SeasonServiceDep):
    """Add teams to season by providing a list of team ids."""
    season = service.addTeams(season_id, data.get("team_ids"))
    return season.to_dict() if season else None


@router.post("/seasons/removeTeams/{season_id}", dependencies=[Depends(require_admin)])
def remove_teams(
    season_id: int, data: Annotated[dict, Body()], service: SeasonServiceDep
):
    """Remove teams from season by providing a list of team ids."""
    season = service.removeTeams(season_id, data.get("team_ids"))
    return season.to_dict() if season else None


@router.get("/seasons")
def get_all(service: SeasonServiceDep):
    """Return all seasons"""
    return [season.to_dict() for season in service.getAll() or []]


@router.post("/seasons/search")
def search_seasons(service: SeasonServiceDep, query: str = ""):
    """Search seasons by criteria using a custom query format."""
    parsed_query = QueryUtil.parseQuery(query)
    if not parsed_query or not parsed_query.elementA:
        raise Exception(f"No valid query found: {query}")
    return [season.to_dict() for season in service.search(parsed_query) or []]


@router.post("/seasons/addMaps/{season_id}", dependencies=[Depends(require_admin)])
def add_maps(season_id: int, data: Annotated[dict, Body()], service: SeasonServiceDep):
    """Add maps to season by providing a list of map ids."""
    season = service.addMaps(season_id, data.get("map_ids"))
    return season.to_dict() if season else None


@router.post("/seasons/removeMaps/{season_id}", dependencies=[Depends(require_admin)])
def remove_maps(
    season_id: int, data: Annotated[dict, Body()], service: SeasonServiceDep
):
    """Remove maps from season by providing a list of map ids."""
    season = service.removeMaps(season_id, data.get("map_ids"))
    return season.to_dict() if season else None


@router.post(
    "/seasons/addUserSignup/{season_id}", dependencies=[Depends(require_admin)]
)
def add_user_signup(
    season_id: int, data: Annotated[dict, Body()], service: SeasonServiceDep
):
    """Add signup users to season by providing a list of user ids."""
    season = service.addUserSignup(season_id, data.get("user_ids"))
    return season.to_dict() if season else None


@router.post(
    "/seasons/removeUserSignup/{season_id}", dependencies=[Depends(require_admin)]
)
def remove_user_signup(
    season_id: int, data: Annotated[dict, Body()], service: SeasonServiceDep
):
    """Remove signup users from season by providing a list of user ids."""
    season = service.removeUserSignup(season_id, data.get("user_ids"))
    return season.to_dict() if season else None


@router.get("/seasons/{season_id}/signups")
def get_season_signups(season_id: int, service: SeasonServiceDep):
    """Retrieve all users signed up for a specific season."""
    return [user.to_dict() for user in service.getSignedUpUsers(season_id) or []]
