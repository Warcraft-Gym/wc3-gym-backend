import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import LadderServiceDep, SeasonServiceDep, require_admin
from app.api.search import SearchQuery
from app.models.map import LadderMapRow
from app.models.relationships import SeasonWeekMapWrite
from app.models.season import (
    SeasonCreate,
    SeasonLadderMapNames,
    SeasonMapIds,
    SeasonPublic,
    SeasonSignupWrite,
    SeasonTeamIds,
    SeasonUpdate,
)
from app.models.user import UserListPublic
from app.models.w3c_ladder_match import LadderSyncResult, SeasonLadder
from app.services.users import W3C_SYNC_WORKERS

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


@router.post("/seasons/{season_id}/teams", dependencies=[Depends(require_admin)])
def add_teams(
    season_id: int, data: SeasonTeamIds, service: SeasonServiceDep
) -> SeasonPublic:
    """Add teams to season by providing a list of team ids."""
    return service.add_teams(season_id, data.team_ids)


@router.delete("/seasons/{season_id}/teams", dependencies=[Depends(require_admin)])
def remove_teams(
    season_id: int, data: SeasonTeamIds, service: SeasonServiceDep
) -> SeasonPublic:
    """Remove teams from season by providing a list of team ids."""
    return service.remove_teams(season_id, data.team_ids)


@router.get("/seasons")
def get_all(
    service: SeasonServiceDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SeasonPublic]:
    """Return one page of seasons, at most 500."""
    return service.get_all(limit=limit, offset=offset)


@router.post("/seasons/search")
def search_seasons(
    service: SeasonServiceDep,
    query: SearchQuery,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SeasonPublic]:
    """Search seasons by criteria using a custom query format."""
    return service.search(query, limit=limit, offset=offset)


@router.post("/seasons/{season_id}/maps", dependencies=[Depends(require_admin)])
def add_maps(
    season_id: int, data: SeasonMapIds, service: SeasonServiceDep
) -> SeasonPublic:
    """Add maps to season by providing a list of map ids."""
    return service.add_maps(season_id, data.map_ids)


@router.delete("/seasons/{season_id}/maps", dependencies=[Depends(require_admin)])
def remove_maps(
    season_id: int, data: SeasonMapIds, service: SeasonServiceDep
) -> SeasonPublic:
    """Remove maps from season by providing a list of map ids."""
    return service.remove_maps(season_id, data.map_ids)


@router.get(
    "/seasons/{season_id}/maps/ladder-import", dependencies=[Depends(require_admin)]
)
def preview_ladder_import(
    season_id: int, service: SeasonServiceDep
) -> list[LadderMapRow]:
    """List every 1v1 ladder map, matched against the maps the app holds."""
    return service.ladder_import_preview(season_id)


@router.post(
    "/seasons/{season_id}/maps/ladder-import", dependencies=[Depends(require_admin)]
)
def apply_ladder_import(
    season_id: int, data: SeasonLadderMapNames, service: SeasonServiceDep
) -> SeasonPublic:
    """Add the named ladder maps to the pool, creating the ones the app misses."""
    return service.import_ladder_maps(season_id, data.names)


@router.put("/seasons/{season_id}/maps/order", dependencies=[Depends(require_admin)])
def set_map_order(
    season_id: int, data: SeasonMapIds, service: SeasonServiceDep
) -> SeasonPublic:
    """Reorder the map pool by listing every map id of it, in the new order."""
    return service.set_map_order(season_id, data.map_ids)


@router.put("/seasons/{season_id}/week-maps", dependencies=[Depends(require_admin)])
def set_week_map(
    season_id: int, data: SeasonWeekMapWrite, service: SeasonServiceDep
) -> SeasonPublic:
    """Name the game 1 map of one playday. A null map clears the playday."""
    return service.set_week_map(season_id, data.playday, data.map_id)


@router.post("/seasons/{season_id}/signups", dependencies=[Depends(require_admin)])
def add_user_signup(
    season_id: int, data: SeasonSignupWrite, service: SeasonServiceDep
) -> SeasonPublic:
    """Add signup users to season by providing a list of user ids.

    An optional "race" names the race they registered on for this season.
    """
    return service.add_user_signup(season_id, data.user_ids, data.race)


@router.delete("/seasons/{season_id}/signups", dependencies=[Depends(require_admin)])
def remove_user_signup(
    season_id: int, data: SeasonSignupWrite, service: SeasonServiceDep
) -> SeasonPublic:
    """Remove signup users from season by providing a list of user ids."""
    return service.remove_user_signup(season_id, data.user_ids)


@router.get("/seasons/{season_id}/signups")
def get_season_signups(
    season_id: int,
    service: SeasonServiceDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[UserListPublic]:
    """Retrieve one page of the users signed up for a season, at most 500."""
    return service.get_signed_up_users(season_id, limit=limit, offset=offset)


@router.post("/seasons/{season_id}/w3c-sync", dependencies=[Depends(require_admin)])
def sync_w3c_season_signups(
    season_id: int,
    service: LadderServiceDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    # one chunk = one worker wave
    limit: Annotated[int, Query(ge=1, le=25)] = W3C_SYNC_WORKERS,
) -> LadderSyncResult:
    """The ladder sync under the path the stats sync had."""
    return service.sync_season(season_id, offset=offset, limit=limit)


@router.post("/seasons/{season_id}/ladder-sync", dependencies=[Depends(require_admin)])
def sync_ladder_season_signups(
    season_id: int,
    service: LadderServiceDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    # one chunk = one worker wave
    limit: Annotated[int, Query(ge=1, le=25)] = W3C_SYNC_WORKERS,
) -> LadderSyncResult:
    """Sync one chunk of the season's players: their stats and their matches.

    The client calls again with next_offset until it answers null. A player
    synced in the last SYNC_MAX_AGE is skipped.
    """
    return service.sync_season(season_id, offset=offset, limit=limit)


@router.get("/seasons/{season_id}/ladder")
def get_season_ladder(season_id: int, service: LadderServiceDep) -> SeasonLadder:
    """The ladder of a season: its teams, its players and its hours."""
    return service.season_ladder(season_id)
