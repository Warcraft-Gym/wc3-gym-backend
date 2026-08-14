import logging
import time
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, File, Response, UploadFile
from fastapi.responses import JSONResponse

from app.api.deps import TeamServiceDep, require_admin, ttl_cache
from app.models.team import TeamCreate, TeamPublic, TeamUpdate
from app.utils.query_util import QueryUtil

logger = logging.getLogger(__name__)

router = APIRouter(tags=["teams"])


@router.post(
    "/teams",
    status_code=201,
    response_model=TeamPublic,
    dependencies=[Depends(require_admin)],
)
def add_team(data: TeamCreate, service: TeamServiceDep) -> TeamPublic:
    """Create a new team with the provided name."""
    return service.create_team(data)


@router.put(
    "/teams/{team_id}",
    response_model=TeamPublic,
    dependencies=[Depends(require_admin)],
)
def update_team(team_id: int, data: TeamUpdate, service: TeamServiceDep) -> TeamPublic:
    """Update the name of an existing team."""
    return service.update_team(team_id, data)


@router.delete(
    "/teams/{team_id}", status_code=204, dependencies=[Depends(require_admin)]
)
def delete_team(team_id: int, service: TeamServiceDep) -> None:
    """Delete a team by its ID."""
    service.delete_team(team_id)


@router.get("/teams/basic")
def get_all_teams_basic(service: TeamServiceDep) -> list[dict[str, Any]]:
    """Retrieve all teams with basic information only (id, name, long_name, discord_role). No user or season data included."""
    return [team.to_dict() for team in service.getAll_basic() or []]


@router.get("/teams/{team_id}")
def get_team(team_id: int, service: TeamServiceDep) -> dict[str, Any] | None:
    """Retrieve a team by its ID."""
    team = service.get_team(team_id)
    return team.to_dict() if team else None


@router.get("/teams/{team_id}/seasons/{season_id}")
def get_team_season(
    team_id: int, season_id: int, service: TeamServiceDep
) -> dict[str, Any] | None:
    """Retrieve a team by its ID with all information related to a specific season"""
    team = service.get_team_season(team_id, season_id)
    return team.to_dict() if team else None


@router.get("/teams/season/{season_id}")
def get_all_teams_season(
    season_id: int, service: TeamServiceDep
) -> list[dict[str, Any]]:
    """Retrieve all teams with all information related to a specific season"""
    return [team.to_dict() for team in service.get_teams_season(season_id) or []]


@router.get("/teams/season/{season_id}/basic")
def get_all_teams_season_basic(
    season_id: int, service: TeamServiceDep
) -> list[dict[str, Any]]:
    """Retrieve all teams with season info but without user data for a specific season"""
    return [team.to_dict() for team in service.get_teams_season_basic(season_id) or []]


@router.post(
    "/teams/addPlayers/{team_id}/seasons/{season_id}",
    dependencies=[Depends(require_admin)],
)
def add_players(
    team_id: int,
    season_id: int,
    data: Annotated[dict, Body()],
    service: TeamServiceDep,
) -> dict[str, Any] | None:
    """Add players to a team for a season using their IDs."""
    team = service.addPlayers(team_id, season_id, data.get("player_ids"))
    return team.to_dict() if team else None


@router.post(
    "/teams/removePlayers/{team_id}/seasons/{season_id}",
    dependencies=[Depends(require_admin)],
)
def remove_players(
    team_id: int,
    season_id: int,
    data: Annotated[dict, Body()],
    service: TeamServiceDep,
) -> dict[str, Any] | None:
    """Removes players from a team for a season using their IDs."""
    team = service.removePlayers(team_id, season_id, data.get("player_ids"))
    return team.to_dict() if team else None


@router.put(
    "/teams/{team_id}/seasons/{season_id}/coaches",
    dependencies=[Depends(require_admin)],
)
def set_coaches(
    team_id: int,
    season_id: int,
    data: Annotated[dict, Body()],
    service: TeamServiceDep,
) -> JSONResponse:
    """Set up to 3 coaches for a team in a specific season. Replaces existing coaches."""
    coach_ids = data.get("coach_ids", [])

    if len(coach_ids) > 3:
        return JSONResponse(
            {"error": "Cannot assign more than 3 coaches per team per season"},
            status_code=400,
        )

    team = service.setCoaches(team_id, season_id, coach_ids)
    if team:
        team = team.to_dict()
    return JSONResponse(team, status_code=200)


@router.get("/teams")
def get_all_teams(service: TeamServiceDep) -> list[dict[str, Any]]:
    """Retrieve all teams."""
    return [team.to_dict() for team in service.getAll() or []]


@router.post("/teams/search")
def search_teams(service: TeamServiceDep, query: str = "") -> list[dict[str, Any]]:
    """Search teams by criteria using a custom query format."""
    parsed_query = QueryUtil.parseQuery(query)
    if not parsed_query or not parsed_query.elementA:
        raise Exception(f"No valid query found: {query}")
    return [team.to_dict() for team in service.search(parsed_query) or []]


@router.post("/teams/w3c_sync/{team_id}/seasons/{season_id}", response_model=None)
def sync_w3c_users_season(
    team_id: int, season_id: int, service: TeamServiceDep
) -> Response | dict[str, Any] | None:
    """Sync w3c information for each user of the team"""
    cache_key = f"w3c_sync:{team_id}:{season_id}"

    if ttl_cache.get(cache_key, 0) > time.time():
        return Response(
            "Sync already performed today", status_code=429, media_type="text/html"
        )

    team = service.syncW3CStatsTeam(team_id, season_id)
    if team:
        team = team.to_dict()

    ttl_cache[cache_key] = time.time() + 86400  # One sync per team and season per day

    team = service.syncW3CStatsTeam(team_id, season_id)
    return team.to_dict() if team else None


@router.post("/teams/{team_id}/image")
def upload_team_image(
    team_id: int,
    service: TeamServiceDep,
    image: Annotated[UploadFile | None, File()] = None,
) -> JSONResponse:
    """Allows a user to upload or modify a team's image stored in binary format"""
    if image is None:
        return JSONResponse({"error": "No image provided"}, status_code=400)

    file_data = image.file.read()  # Read binary data

    service.update_team_icon(team_id, file_data)

    return JSONResponse({"message": "Image uploaded successfully"}, status_code=200)


@router.get("/teams/{team_id}/image")
def get_team_image(team_id: int, service: TeamServiceDep) -> Response:
    """Fetches and returns the stored binary image for a team"""
    team_icon = service.get_team_icon(team_id)
    if not team_icon:
        return JSONResponse({"error": "Image not found"}, status_code=404)

    # Browsers cache the image for one hour.
    return Response(
        content=team_icon,
        media_type="image/png",
        headers={
            "Cache-Control": "public, max-age=3600",
            "ETag": f"team-{team_id}",
        },
    )
