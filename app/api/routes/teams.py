import hashlib
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile
from fastapi.responses import RedirectResponse

from app.api.deps import (
    AvailabilityServiceDep,
    LadderServiceDep,
    RequireCaptain,
    TeamServiceDep,
    UserServiceDep,
    require_admin,
)
from app.api.search import SearchQuery
from app.core.exceptions import ApiError, BadRequestError, NotFoundError
from app.models.team import (
    TeamCaptainIds,
    TeamCreate,
    TeamPlayerIds,
    TeamPublic,
    TeamUpdate,
)
from app.models.user_season_availability import (
    TeamAvailabilityWrite,
    UserSeasonAvailabilityPublic,
)
from app.models.w3c_stats import W3CSyncResult
from app.services import blob
from app.services.users import SYNC_MAX_AGE

logger = logging.getLogger(__name__)

router = APIRouter(tags=["teams"])


def _own_team(claims: dict[str, Any], team_id: int) -> None:
    """A captain reaches their own team; an admin reaches any."""
    if claims.get("role") == "admin" or claims["sub"] == "admin":
        return
    if claims.get("team_id") != team_id:
        raise ApiError(403, {"error": "Not your team"})


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
    return service.get_all_basic(limit=limit, offset=offset)


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


@router.get("/teams/{team_id}/seasons/{season_id}/availability")
def get_team_availability(
    team_id: int,
    season_id: int,
    claims: RequireCaptain,
    service: AvailabilityServiceDep,
) -> list[UserSeasonAvailabilityPublic]:
    """The weeks the players of that team season have answered for."""
    _own_team(claims, team_id)
    return service.for_team(team_id, season_id)


@router.put("/teams/{team_id}/seasons/{season_id}/availability")
def set_team_availability(
    team_id: int,
    season_id: int,
    data: TeamAvailabilityWrite,
    claims: RequireCaptain,
    service: AvailabilityServiceDep,
    user_service: UserServiceDep,
) -> list[UserSeasonAvailabilityPublic]:
    """Answer one week for a player of the team, as their captain."""
    _own_team(claims, team_id)
    if not service.on_roster(team_id, season_id, data.user_id):
        raise BadRequestError(f"Player {data.user_id} is not on this team this season")
    callers = user_service.find_by_discord_id(str(claims["sub"]))
    if not callers:
        raise NotFoundError("user_not_found")
    return service.set(
        data.user_id,
        season_id,
        data.playday,
        data.available,
        set_by_user_id=callers[0].id,
    )


@router.get("/teams/season/{season_id}")
def get_all_teams_season(
    season_id: int,
    service: TeamServiceDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TeamPublic]:
    """Retrieve one page of the teams of a season, at most 500, with all information related to that season"""
    return service.get_teams_season(season_id, limit=limit, offset=offset)


@router.get("/teams/season/{season_id}/basic")
def get_all_teams_season_basic(
    season_id: int,
    service: TeamServiceDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TeamPublic]:
    """Retrieve one page of the teams of a season, at most 500, with season info but without user data"""
    return service.get_teams_season_basic(season_id, limit=limit, offset=offset)


@router.post(
    "/teams/{team_id}/seasons/{season_id}/players",
    dependencies=[Depends(require_admin)],
)
def add_players(
    team_id: int,
    season_id: int,
    data: TeamPlayerIds,
    service: TeamServiceDep,
) -> TeamPublic:
    """Add players to a team for a season using their IDs."""
    return service.add_players(team_id, season_id, data.player_ids)


@router.delete(
    "/teams/{team_id}/seasons/{season_id}/players",
    dependencies=[Depends(require_admin)],
)
def remove_players(
    team_id: int,
    season_id: int,
    data: TeamPlayerIds,
    service: TeamServiceDep,
) -> TeamPublic:
    """Removes players from a team for a season using their IDs."""
    return service.remove_players(team_id, season_id, data.player_ids)


@router.put(
    "/teams/{team_id}/seasons/{season_id}/captains",
    dependencies=[Depends(require_admin)],
)
def set_captains(
    team_id: int,
    season_id: int,
    data: TeamCaptainIds,
    service: TeamServiceDep,
) -> TeamPublic:
    """Replace the captains a team has in a season, however many that is."""
    return service.set_captains(team_id, season_id, data.captain_ids)


@router.get("/teams")
def get_all_teams(
    service: TeamServiceDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TeamPublic]:
    """Retrieve one page of teams, at most 500."""
    return service.get_all(limit=limit, offset=offset)


@router.post("/teams/search")
def search_teams(
    service: TeamServiceDep,
    query: SearchQuery,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TeamPublic]:
    """Search teams by criteria using a custom query format."""
    return service.search(query, limit=limit, offset=offset)


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
    """Answer the team logo: the blob it lives in, or the stored bytes until it has moved."""
    url = service.get_icon_url(team_id)
    if url:
        # Not cacheable: a replacement gets a new blob URL and deletes the old one, so a cached
        # redirect would send every viewer to a blob that no longer exists until it expired. The
        # blob itself carries a year, so only this hop is paid again. Callers reading icon_url
        # from the team answer skip the hop entirely.
        return RedirectResponse(url, headers={"Cache-Control": "no-store"})

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

    # a read must not fail on a type the upload would refuse: some stored rows predate any check
    return Response(
        content=team_icon, media_type=blob.stored_type(team_icon), headers=headers
    )
