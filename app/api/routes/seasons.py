import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import LadderServiceDep, SeasonServiceDep, require_admin
from app.api.search import SearchQuery
from app.models.ladder_achievement import (
    SeasonAchievementPublic,
    SeasonAchievementWrite,
    catalogue,
)
from app.models.map import LadderMapNames, LadderMapRow
from app.models.relationships import SeasonRoundWrite
from app.models.season import (
    SeasonCreate,
    SeasonMapIds,
    SeasonPublic,
    SeasonSignupRemove,
    SeasonSignupUpdate,
    SeasonSignupWrite,
    SeasonTeamIds,
    SeasonUpdate,
)
from app.models.user import UserListPublic
from app.models.w3c_ladder_match import LadderSyncResult, SeasonLadder, SeasonPlayer
from app.services.users import W3C_SYNC_WORKERS

logger = logging.getLogger(__name__)

router = APIRouter(tags=["seasons"])


@router.post(
    "/seasons",
    status_code=201,
    response_model=SeasonPublic,
    deprecated=True,
    dependencies=[Depends(require_admin)],
)
def add_season(data: SeasonCreate, service: SeasonServiceDep) -> SeasonPublic:
    """Create a new season with the provided name."""
    return service.add(data)


@router.put(
    "/seasons/{event_id}",
    response_model=SeasonPublic,
    deprecated=True,
    dependencies=[Depends(require_admin)],
)
def update_season(
    event_id: int, data: SeasonUpdate, service: SeasonServiceDep
) -> SeasonPublic:
    """Update the name of an existing season."""
    return service.update(event_id, data)


@router.delete(
    "/seasons/{event_id}",
    status_code=204,
    deprecated=True,
    dependencies=[Depends(require_admin)],
)
def delete_season(event_id: int, service: SeasonServiceDep) -> None:
    """Delete a season by its ID."""
    service.delete(event_id)


@router.get("/seasons/{event_id}", deprecated=True)
def get_season(event_id: int, service: SeasonServiceDep) -> SeasonPublic:
    """Retrieve a season by its ID."""
    return service.get(event_id)


@router.post(
    "/events/{event_id}/teams", tags=["events"], dependencies=[Depends(require_admin)]
)
@router.post(
    "/seasons/{event_id}/teams",
    deprecated=True,
    dependencies=[Depends(require_admin)],
)
def add_teams(
    event_id: int, data: SeasonTeamIds, service: SeasonServiceDep
) -> SeasonPublic:
    """Add teams to season by providing a list of team ids."""
    return service.add_teams(event_id, data.team_ids)


@router.delete(
    "/events/{event_id}/teams", tags=["events"], dependencies=[Depends(require_admin)]
)
@router.delete(
    "/seasons/{event_id}/teams",
    deprecated=True,
    dependencies=[Depends(require_admin)],
)
def remove_teams(
    event_id: int, data: SeasonTeamIds, service: SeasonServiceDep
) -> SeasonPublic:
    """Remove teams from season by providing a list of team ids."""
    return service.remove_teams(event_id, data.team_ids)


@router.get("/seasons", deprecated=True)
def get_all(
    service: SeasonServiceDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SeasonPublic]:
    """Return one page of seasons, at most 500."""
    return service.get_all(limit=limit, offset=offset)


@router.post("/seasons/search", deprecated=True)
def search_seasons(
    service: SeasonServiceDep,
    query: SearchQuery,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SeasonPublic]:
    """Search seasons by criteria using a custom query format."""
    return service.search(query, limit=limit, offset=offset)


@router.post(
    "/events/{event_id}/maps", tags=["events"], dependencies=[Depends(require_admin)]
)
@router.post(
    "/seasons/{event_id}/maps",
    deprecated=True,
    dependencies=[Depends(require_admin)],
)
def add_maps(
    event_id: int, data: SeasonMapIds, service: SeasonServiceDep
) -> SeasonPublic:
    """Add maps to season by providing a list of map ids."""
    return service.add_maps(event_id, data.map_ids)


@router.delete(
    "/events/{event_id}/maps", tags=["events"], dependencies=[Depends(require_admin)]
)
@router.delete(
    "/seasons/{event_id}/maps",
    deprecated=True,
    dependencies=[Depends(require_admin)],
)
def remove_maps(
    event_id: int, data: SeasonMapIds, service: SeasonServiceDep
) -> SeasonPublic:
    """Remove maps from season by providing a list of map ids."""
    return service.remove_maps(event_id, data.map_ids)


@router.get(
    "/events/{event_id}/maps/ladder-import",
    tags=["events"],
    dependencies=[Depends(require_admin)],
)
@router.get(
    "/seasons/{event_id}/maps/ladder-import",
    deprecated=True,
    dependencies=[Depends(require_admin)],
)
def preview_ladder_import(
    event_id: int, service: SeasonServiceDep
) -> list[LadderMapRow]:
    """List every 1v1 ladder map, matched against the maps the app holds."""
    return service.ladder_import_preview(event_id)


@router.post(
    "/events/{event_id}/maps/ladder-import",
    tags=["events"],
    dependencies=[Depends(require_admin)],
)
@router.post(
    "/seasons/{event_id}/maps/ladder-import",
    deprecated=True,
    dependencies=[Depends(require_admin)],
)
def apply_ladder_import(
    event_id: int, data: LadderMapNames, service: SeasonServiceDep
) -> SeasonPublic:
    """Add the named ladder maps to the pool, creating the ones the app misses."""
    return service.import_ladder_maps(event_id, data.names)


@router.put(
    "/events/{event_id}/maps/order",
    tags=["events"],
    dependencies=[Depends(require_admin)],
)
@router.put(
    "/seasons/{event_id}/maps/order",
    deprecated=True,
    dependencies=[Depends(require_admin)],
)
def set_map_order(
    event_id: int, data: SeasonMapIds, service: SeasonServiceDep
) -> SeasonPublic:
    """Reorder the map pool by listing every map id of it, in the new order."""
    return service.set_map_order(event_id, data.map_ids)


@router.put(
    "/events/{event_id}/rounds",
    tags=["events"],
    dependencies=[Depends(require_admin)],
)
@router.put(
    "/seasons/{event_id}/rounds",
    deprecated=True,
    dependencies=[Depends(require_admin)],
)
def set_round(
    event_id: int, data: SeasonRoundWrite, service: SeasonServiceDep
) -> SeasonPublic:
    """Set the dates and the game 1 map of one round. A field left out keeps its value."""
    return service.set_round(event_id, data)


@router.post(
    "/events/{event_id}/signups",
    tags=["events"],
    dependencies=[Depends(require_admin)],
)
@router.post(
    "/seasons/{event_id}/signups",
    deprecated=True,
    dependencies=[Depends(require_admin)],
)
def add_user_signup(
    event_id: int, data: SeasonSignupWrite, service: SeasonServiceDep
) -> SeasonPublic:
    """Add signup users to season by providing a list of user ids.

    The "race" names the race they registered on for this season.
    """
    return service.add_user_signup(event_id, data.user_ids, data.race)


@router.delete(
    "/events/{event_id}/signups",
    tags=["events"],
    dependencies=[Depends(require_admin)],
)
@router.delete(
    "/seasons/{event_id}/signups",
    deprecated=True,
    dependencies=[Depends(require_admin)],
)
def remove_user_signup(
    event_id: int, data: SeasonSignupRemove, service: SeasonServiceDep
) -> SeasonPublic:
    """Remove signup users from season by providing a list of user ids."""
    return service.remove_user_signup(event_id, data.user_ids)


@router.put(
    "/events/{event_id}/signups/{user_id}",
    tags=["events"],
    dependencies=[Depends(require_admin)],
)
@router.put(
    "/seasons/{event_id}/signups/{user_id}",
    deprecated=True,
    dependencies=[Depends(require_admin)],
)
def update_user_signup(
    event_id: int, user_id: int, data: SeasonSignupUpdate, service: SeasonServiceDep
) -> SeasonPublic:
    """Set the draft position, the pick-list flag or the race of one signup."""
    return service.update_signup(event_id, user_id, data)


@router.get("/events/{event_id}/signups", tags=["events"])
@router.get("/seasons/{event_id}/signups", deprecated=True)
def get_season_signups(
    event_id: int,
    service: SeasonServiceDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[UserListPublic]:
    """Retrieve one page of the users signed up for a season, at most 500."""
    return service.get_signed_up_users(event_id, limit=limit, offset=offset)


@router.post(
    "/seasons/{event_id}/w3c-sync",
    deprecated=True,
    dependencies=[Depends(require_admin)],
)
def sync_w3c_season_signups(
    event_id: int,
    service: LadderServiceDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    # one chunk = one worker wave
    limit: Annotated[int, Query(ge=1, le=25)] = W3C_SYNC_WORKERS,
) -> LadderSyncResult:
    """The ladder sync under the path the stats sync had."""
    return service.sync_season(event_id, offset=offset, limit=limit)


@router.post(
    "/events/{event_id}/ladder-sync",
    tags=["events"],
    dependencies=[Depends(require_admin)],
)
@router.post(
    "/seasons/{event_id}/ladder-sync",
    deprecated=True,
    dependencies=[Depends(require_admin)],
)
def sync_ladder_season_signups(
    event_id: int,
    service: LadderServiceDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    # one chunk = one worker wave
    limit: Annotated[int, Query(ge=1, le=25)] = W3C_SYNC_WORKERS,
) -> LadderSyncResult:
    """Sync one chunk of the season's players: their stats and their matches.

    The client calls again with next_offset until it answers null. A player
    synced in the last SYNC_MAX_AGE is skipped.
    """
    return service.sync_season(event_id, offset=offset, limit=limit)


@router.get("/achievements")
def get_achievement_catalogue() -> list[SeasonAchievementPublic]:
    """Every achievement rule at its default price and numbers."""
    return catalogue()


@router.get("/events/{event_id}/achievements", tags=["events"])
@router.get("/seasons/{event_id}/achievements", deprecated=True)
def get_season_achievements(
    event_id: int, service: SeasonServiceDep
) -> list[SeasonAchievementPublic]:
    """The rules this season pays, with its prices and numbers."""
    return service.achievements(event_id)


@router.put(
    "/events/{event_id}/achievements",
    tags=["events"],
    dependencies=[Depends(require_admin)],
)
@router.put(
    "/seasons/{event_id}/achievements",
    deprecated=True,
    dependencies=[Depends(require_admin)],
)
def set_season_achievements(
    event_id: int, data: list[SeasonAchievementWrite], service: SeasonServiceDep
) -> list[SeasonAchievementPublic]:
    """Replace the season's set with these rows."""
    return service.set_achievements(event_id, data)


@router.get("/events/{event_id}/ladder", tags=["events"])
@router.get("/seasons/{event_id}/ladder", deprecated=True)
def get_season_ladder(
    event_id: int, service: LadderServiceDep, response: Response
) -> SeasonLadder:
    """The ladder of a season: its teams, its players and its hours."""
    # matches change once a day at the cron; the edge serves every viewer one read
    response.headers["Cache-Control"] = "public, s-maxage=3600"
    # the edge keeps the headers of the request that filled it, and CORSMiddleware
    # writes none when that request has no Origin, so a browser reads a copy it blocks
    response.headers["Access-Control-Allow-Origin"] = "*"
    return service.season_ladder(event_id)


@router.get("/events/{event_id}/ladder/players", tags=["events"])
@router.get("/seasons/{event_id}/ladder/players", deprecated=True)
def get_season_ladder_players(
    event_id: int, service: LadderServiceDep
) -> list[SeasonPlayer]:
    """Every signup of the season with his ladder record, without the achievements."""
    return service.season_players(event_id)
