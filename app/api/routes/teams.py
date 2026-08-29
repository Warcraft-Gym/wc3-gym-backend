import hashlib
import logging
from typing import Annotated

from fastapi import APIRouter, Body, Depends, File, Query, Request, Response, UploadFile

from app.api.deps import LadderServiceDep, TeamServiceDep, require_admin
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.query import QueryUtil
from app.models.team import TeamCreate, TeamPublic, TeamUpdate
from app.models.w3c_stats import W3CSyncResult
from app.services.users import SYNC_MAX_AGE

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
    return service.add(data)


@router.put(
    "/teams/{team_id}",
    response_model=TeamPublic,
    dependencies=[Depends(require_admin)],
)
def update_team(team_id: int, data: TeamUpdate, service: TeamServiceDep) -> TeamPublic:
    """Update the name of an existing team."""
    return service.update(team_id, data)


@router.delete(
    "/teams/{team_id}", status_code=204, dependencies=[Depends(require_admin)]
)
def delete_team(team_id: int, service: TeamServiceDep) -> None:
    """Delete a team by its ID."""
    service.delete(team_id)


@router.get("/teams/basic")
def get_all_teams_basic(
    service: TeamServiceDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TeamPublic]:
    """Retrieve one page of teams, at most 500, with basic information only (id, name, long_name, discord_role). No user or season data included."""
    return service.get_all_basic(limit=limit, offset=offset) or []


@router.get("/teams/{team_id}")
def get_team(team_id: int, service: TeamServiceDep) -> TeamPublic:
    """Retrieve a team by its ID."""
    return service.get(team_id)


@router.get("/teams/{team_id}/seasons/{season_id}")
def get_team_season(
    team_id: int, season_id: int, service: TeamServiceDep
) -> TeamPublic:
    """Retrieve a team by its ID with all information related to a specific season"""
    return service.get_with_nested_users_by_season(team_id, season_id)


@router.get("/teams/season/{season_id}")
def get_all_teams_season(
    season_id: int,
    service: TeamServiceDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TeamPublic]:
    """Retrieve one page of the teams of a season, at most 500, with all information related to that season"""
    return service.get_teams_season(season_id, limit=limit, offset=offset) or []


@router.get("/teams/season/{season_id}/basic")
def get_all_teams_season_basic(
    season_id: int,
    service: TeamServiceDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TeamPublic]:
    """Retrieve one page of the teams of a season, at most 500, with season info but without user data"""
    return service.get_teams_season_basic(season_id, limit=limit, offset=offset) or []


@router.post(
    "/teams/{team_id}/seasons/{season_id}/players",
    dependencies=[Depends(require_admin)],
)
def add_players(
    team_id: int,
    season_id: int,
    data: Annotated[dict, Body()],
    service: TeamServiceDep,
) -> TeamPublic:
    """Add players to a team for a season using their IDs."""
    return service.add_players(team_id, season_id, data.get("player_ids"))


@router.delete(
    "/teams/{team_id}/seasons/{season_id}/players",
    dependencies=[Depends(require_admin)],
)
def remove_players(
    team_id: int,
    season_id: int,
    data: Annotated[dict, Body()],
    service: TeamServiceDep,
) -> TeamPublic:
    """Removes players from a team for a season using their IDs."""
    return service.remove_players(team_id, season_id, data.get("player_ids"))


@router.put(
    "/teams/{team_id}/seasons/{season_id}/coaches",
    dependencies=[Depends(require_admin)],
)
def set_coaches(
    team_id: int,
    season_id: int,
    data: Annotated[dict, Body()],
    service: TeamServiceDep,
) -> TeamPublic:
    """Set up to 3 coaches for a team in a specific season. Replaces existing coaches."""
    coach_ids = data.get("coach_ids", [])

    if len(coach_ids) > 3:
        raise BadRequestError("Cannot assign more than 3 coaches per team per season")

    return service.set_coaches(team_id, season_id, coach_ids)


@router.get("/teams")
def get_all_teams(
    service: TeamServiceDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TeamPublic]:
    """Retrieve one page of teams, at most 500."""
    return service.get_all(limit=limit, offset=offset) or []


@router.post("/teams/search")
def search_teams(
    service: TeamServiceDep,
    query: str = "",
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TeamPublic]:
    """Search teams by criteria using a custom query format."""
    parsed_query = QueryUtil.parse_query(query)
    if not parsed_query or not parsed_query.elementA:
        raise BadRequestError(f"No valid query found: {query}")
    return service.search(parsed_query, limit=limit, offset=offset) or []


@router.post(
    "/teams/{team_id}/seasons/{season_id}/w3c-sync",
    dependencies=[Depends(require_admin)],
)
def sync_w3c_users_season(
    team_id: int, season_id: int, service: TeamServiceDep, ladder: LadderServiceDep
) -> W3CSyncResult:
    """Sync the stats and the matches of each player of the team, and report
    every player."""
    users = service.season_players(team_id, season_id)
    return ladder.sync_season_users(season_id, users, SYNC_MAX_AGE)


@router.post("/teams/{team_id}/image", dependencies=[Depends(require_admin)])
def upload_team_image(
    team_id: int,
    service: TeamServiceDep,
    image: Annotated[UploadFile | None, File()] = None,
) -> dict[str, str]:
    """Allows a user to upload or modify a team's image stored in binary format"""
    if image is None:
        raise BadRequestError("No image provided")

    file_data = image.file.read()  # Read binary data

    service.update_icon(team_id, file_data)

    return {"message": "Image uploaded successfully"}


@router.get("/teams/{team_id}/image")
def get_team_image(team_id: int, request: Request, service: TeamServiceDep) -> Response:
    """Fetches and returns the stored binary image for a team"""
    team_icon = service.get_icon(team_id)
    if not team_icon:
        raise NotFoundError("Image not found")

    # The tag is the content, so a replaced icon answers a new one.
    etag = f'"{hashlib.sha256(team_icon).hexdigest()}"'
    headers = {"Cache-Control": "public, max-age=86400", "ETag": etag}
    if etag in [
        tag.strip() for tag in request.headers.get("if-none-match", "").split(",")
    ]:
        return Response(status_code=304, headers=headers)

    return Response(content=team_icon, media_type="image/png", headers=headers)
