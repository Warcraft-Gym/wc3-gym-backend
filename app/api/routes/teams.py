import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from fastapi.responses import RedirectResponse

from app.api.deps import (
    AvailabilityServiceDep,
    LadderServiceDep,
    RequireCaptain,
    TeamServiceDep,
    UserServiceDep,
    claim_seats,
    edge_cache,
    event_edge_cache,
    require_admin,
)
from app.api.search import SearchQuery
from app.core.exceptions import ApiError, BadRequestError, NotFoundError
from app.core.security import is_admin
from app.models.round_availability import (
    RoundAvailabilityPublic,
    TeamAvailabilityAllWrite,
    TeamAvailabilityWrite,
)
from app.models.team import (
    TeamCaptainIds,
    TeamCreate,
    TeamPlayerIds,
    TeamPublic,
    TeamUpdate,
)
from app.models.w3c_stats import W3CSyncResult
from app.services.users import SYNC_MAX_AGE

logger = logging.getLogger(__name__)

router = APIRouter(tags=["teams"])


def _own_team(claims: dict[str, Any], team_id: int, event_id: int) -> None:
    """A captain reaches a team they captain in that event; an admin reaches any."""
    if is_admin(claims):
        return
    if (team_id, event_id) not in claim_seats(claims):
        raise ApiError(403, {"error": "Not your team"})


# League-owned team collection.
@router.post(
    "/leagues/{league_id}/teams",
    status_code=201,
    response_model=TeamPublic,
    dependencies=[Depends(require_admin)],
)
def add_team(data: TeamCreate, service: TeamServiceDep, league_id: int) -> TeamPublic:
    """Create a team owned by a league."""
    return service.add(league_id, data)


@router.get("/leagues/{league_id}/teams/basic")
def get_all_teams_basic(
    service: TeamServiceDep,
    response: Response,
    league_id: int,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TeamPublic]:
    """One page of a league's teams without roster users."""
    edge_cache(response, "running")
    return service.get_all_basic(limit=limit, offset=offset, league_id=league_id)


@router.post("/leagues/{league_id}/teams/search")
def search_teams(
    service: TeamServiceDep,
    query: SearchQuery,
    league_id: int,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TeamPublic]:
    """Search within one league's teams."""
    return service.search(query, limit=limit, offset=offset, league_id=league_id)


@router.get("/leagues/{league_id}/teams")
def get_all_teams(
    service: TeamServiceDep,
    response: Response,
    league_id: int,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TeamPublic]:
    """Retrieve one page of a league's teams."""
    edge_cache(response, "running")
    return service.get_all(limit=limit, offset=offset, league_id=league_id)


# Event-owned team data.
@router.get("/events/{event_id}/teams/basic", tags=["events"])
def get_all_event_teams_basic(
    event_id: int,
    service: TeamServiceDep,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TeamPublic]:
    """One page of event teams with event standings and no users, 50 a page."""
    event_edge_cache(response, event_id)
    return service.get_teams_season_basic(event_id, limit=limit, offset=offset)


@router.get("/events/{event_id}/teams", tags=["events"])
def get_all_event_teams(
    event_id: int,
    service: TeamServiceDep,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TeamPublic]:
    """One page of event teams with that event's roster and captains, 50 a page."""
    event_edge_cache(response, event_id)
    return service.get_teams_season(event_id, limit=limit, offset=offset)


@router.get("/events/{event_id}/teams/{team_id}", tags=["events"])
def get_event_team(
    event_id: int, team_id: int, service: TeamServiceDep, response: Response
) -> TeamPublic:
    """Retrieve one event team with that event's roster, captains and stats."""
    event_edge_cache(response, event_id)
    return service.get_with_nested_users_by_season(team_id, event_id)


@router.get("/events/{event_id}/teams/{team_id}/availability", tags=["events"])
def get_team_availability(
    event_id: int,
    team_id: int,
    claims: RequireCaptain,
    service: AvailabilityServiceDep,
    teams: TeamServiceDep,
) -> list[RoundAvailabilityPublic]:
    """The rounds this event team's players have answered for."""
    _own_team(claims, team_id, event_id)
    teams.ensure_event_team(team_id, event_id)
    return service.for_team(team_id, event_id)


@router.put("/events/{event_id}/teams/{team_id}/availability", tags=["events"])
def set_team_availability(
    event_id: int,
    team_id: int,
    data: TeamAvailabilityWrite,
    claims: RequireCaptain,
    service: AvailabilityServiceDep,
    teams: TeamServiceDep,
    user_service: UserServiceDep,
) -> list[RoundAvailabilityPublic]:
    """Answer one round for a player of the event team, as their captain."""
    _own_team(claims, team_id, event_id)
    teams.ensure_event_team(team_id, event_id)
    if not service.on_roster(team_id, event_id, data.user_id):
        raise BadRequestError(
            f"Player {data.user_id} is not on this team in this event"
        )
    caller_id = user_service.id_by_discord_id(str(claims["sub"]))
    if caller_id is None:
        raise NotFoundError("user_not_found")
    return service.set(
        data.user_id,
        event_id,
        data.playday,
        data.available,
        set_by_user_id=caller_id,
    )


@router.put("/events/{event_id}/teams/{team_id}/availability/all", tags=["events"])
def set_team_availability_all(
    event_id: int,
    team_id: int,
    data: TeamAvailabilityAllWrite,
    claims: RequireCaptain,
    service: AvailabilityServiceDep,
    teams: TeamServiceDep,
    user_service: UserServiceDep,
) -> list[RoundAvailabilityPublic]:
    """Sit a player of the event team out of every round that has not ended.

    A null answer clears those rounds again.
    """
    _own_team(claims, team_id, event_id)
    teams.ensure_event_team(team_id, event_id)
    if not service.on_roster(team_id, event_id, data.user_id):
        raise BadRequestError(
            f"Player {data.user_id} is not on this team in this event"
        )
    caller_id = user_service.id_by_discord_id(str(claims["sub"]))
    if caller_id is None:
        raise NotFoundError("user_not_found")
    return service.set_all(
        data.user_id, event_id, data.available, set_by_user_id=caller_id
    )


@router.post(
    "/events/{event_id}/teams/{team_id}/players",
    tags=["events"],
    dependencies=[Depends(require_admin)],
)
def add_players(
    event_id: int, team_id: int, data: TeamPlayerIds, service: TeamServiceDep
) -> TeamPublic:
    """Add players to an event team."""
    return service.add_players(team_id, event_id, data.player_ids)


@router.delete(
    "/events/{event_id}/teams/{team_id}/players",
    tags=["events"],
    dependencies=[Depends(require_admin)],
)
def remove_players(
    event_id: int, team_id: int, data: TeamPlayerIds, service: TeamServiceDep
) -> TeamPublic:
    """Remove players from an event team."""
    return service.remove_players(team_id, event_id, data.player_ids)


@router.put(
    "/events/{event_id}/teams/{team_id}/captains",
    tags=["events"],
    dependencies=[Depends(require_admin)],
)
def set_captains(
    event_id: int, team_id: int, data: TeamCaptainIds, service: TeamServiceDep
) -> TeamPublic:
    """Replace the captains of an event team."""
    return service.set_captains(team_id, event_id, data.captain_ids)


@router.post(
    "/events/{event_id}/teams/{team_id}/ladder-sync",
    tags=["events"],
    dependencies=[Depends(require_admin)],
)
def sync_event_team_ladder(
    event_id: int,
    team_id: int,
    service: TeamServiceDep,
    ladder: LadderServiceDep,
) -> W3CSyncResult:
    """Sync every player of an event team from the ladder."""
    users = service.season_players(team_id, event_id)
    return ladder.sync_season_users(event_id, users, SYNC_MAX_AGE)


# League-owned team item routes. Keep these after /basic and /search so the
# literal paths win over {team_id}.
@router.get("/leagues/{league_id}/teams/{team_id}")
def get_team(
    team_id: int,
    service: TeamServiceDep,
    response: Response,
    league_id: int,
) -> TeamPublic:
    """Retrieve one team from its league."""
    edge_cache(response, "running")
    return service.get(team_id, league_id=league_id)


@router.put(
    "/leagues/{league_id}/teams/{team_id}", dependencies=[Depends(require_admin)]
)
def update_team(
    team_id: int,
    data: TeamUpdate,
    service: TeamServiceDep,
    league_id: int,
) -> TeamPublic:
    """Update a team in its league."""
    return service.update(team_id, data, league_id=league_id)


@router.delete(
    "/leagues/{league_id}/teams/{team_id}",
    status_code=204,
    dependencies=[Depends(require_admin)],
)
def delete_team(team_id: int, service: TeamServiceDep, league_id: int) -> None:
    """Delete a team from its league."""
    service.delete(team_id, league_id=league_id)


@router.post(
    "/leagues/{league_id}/teams/{team_id}/image",
    dependencies=[Depends(require_admin)],
)
def upload_team_image(
    team_id: int,
    service: TeamServiceDep,
    league_id: int,
    image: Annotated[UploadFile | None, File()] = None,
) -> dict[str, str]:
    """Upload or replace a team's public image."""
    if image is None:
        raise BadRequestError("No image provided")
    service.update_icon(team_id, image.file.read(), league_id=league_id)
    return {"message": "Image uploaded successfully"}


@router.get("/leagues/{league_id}/teams/{team_id}/image")
@router.get("/teams/{team_id}/image", deprecated=True)
def get_team_image(
    team_id: int, service: TeamServiceDep, league_id: int | None = None
) -> RedirectResponse:
    """Send the caller to the blob the team logo lives in."""
    url = service.get_icon_url(team_id, league_id=league_id)
    if not url:
        raise NotFoundError("Image not found")
    return RedirectResponse(url, headers={"Cache-Control": "no-store"})
