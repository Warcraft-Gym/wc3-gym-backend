import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import RedirectResponse

from app.api.deps import (
    AvailabilityServiceDep,
    LadderServiceDep,
    RequireCaptain,
    TeamServiceDep,
    UserServiceDep,
    claim_seats,
    require_admin,
)
from app.api.search import SearchQuery
from app.core.exceptions import ApiError, BadRequestError, NotFoundError
from app.models.round_availability import (
    RoundAvailabilityPublic,
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
    if claims.get("role") == "admin" or claims["sub"] == "admin":
        return
    if (team_id, event_id) not in claim_seats(claims):
        raise ApiError(403, {"error": "Not your team"})


def _league_id(league_id: int | None, service: TeamServiceDep) -> int:
    """Keep the old GNL-only create working while consumers move to leagues."""
    return league_id if league_id is not None else service.legacy_gnl_league_id()


# League-owned team collection. The unscoped forms are compatibility aliases.
@router.post(
    "/leagues/{league_id}/teams",
    status_code=201,
    response_model=TeamPublic,
    dependencies=[Depends(require_admin)],
)
@router.post(
    "/teams",
    status_code=201,
    response_model=TeamPublic,
    deprecated=True,
    dependencies=[Depends(require_admin)],
)
def add_team(
    data: TeamCreate, service: TeamServiceDep, league_id: int | None = None
) -> TeamPublic:
    """Create a team owned by a league."""
    return service.add(_league_id(league_id, service), data)


@router.get("/leagues/{league_id}/teams/basic")
@router.get("/teams/basic", deprecated=True)
def get_all_teams_basic(
    service: TeamServiceDep,
    league_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TeamPublic]:
    """One page of a league's teams without roster users."""
    return service.get_all_basic(limit=limit, offset=offset, league_id=league_id)


@router.post("/leagues/{league_id}/teams/search")
@router.post("/teams/search", deprecated=True)
def search_teams(
    service: TeamServiceDep,
    query: SearchQuery,
    league_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TeamPublic]:
    """Search within one league's teams."""
    return service.search(query, limit=limit, offset=offset, league_id=league_id)


@router.get("/leagues/{league_id}/teams")
@router.get("/teams", deprecated=True)
def get_all_teams(
    service: TeamServiceDep,
    league_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TeamPublic]:
    """Retrieve one page of a league's teams."""
    return service.get_all(limit=limit, offset=offset, league_id=league_id)


# Event-owned team data. The season-named forms are compatibility aliases.
@router.get("/events/{event_id}/teams/basic", tags=["events"])
@router.get("/teams/season/{event_id}/basic", deprecated=True)
def get_all_event_teams_basic(
    event_id: int,
    service: TeamServiceDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TeamPublic]:
    """One page of event teams with event standings and no users."""
    return service.get_teams_season_basic(event_id, limit=limit, offset=offset)


@router.get("/events/{event_id}/teams", tags=["events"])
@router.get("/teams/season/{event_id}", deprecated=True)
def get_all_event_teams(
    event_id: int,
    service: TeamServiceDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TeamPublic]:
    """One page of event teams with that event's roster and captains."""
    return service.get_teams_season(event_id, limit=limit, offset=offset)


@router.get("/events/{event_id}/teams/{team_id}", tags=["events"])
@router.get("/teams/{team_id}/seasons/{event_id}", deprecated=True)
def get_event_team(event_id: int, team_id: int, service: TeamServiceDep) -> TeamPublic:
    """Retrieve one event team with that event's roster, captains and stats."""
    return service.get_with_nested_users_by_season(team_id, event_id)


@router.get("/events/{event_id}/teams/{team_id}/availability", tags=["events"])
@router.get("/teams/{team_id}/seasons/{event_id}/availability", deprecated=True)
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
@router.put("/teams/{team_id}/seasons/{event_id}/availability", deprecated=True)
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
        raise BadRequestError(f"Player {data.user_id} is not on this event team")
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


@router.post(
    "/events/{event_id}/teams/{team_id}/players",
    tags=["events"],
    dependencies=[Depends(require_admin)],
)
@router.post(
    "/teams/{team_id}/seasons/{event_id}/players",
    deprecated=True,
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
@router.delete(
    "/teams/{team_id}/seasons/{event_id}/players",
    deprecated=True,
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
@router.put(
    "/teams/{team_id}/seasons/{event_id}/captains",
    deprecated=True,
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
@router.post(
    "/teams/{team_id}/seasons/{event_id}/w3c-sync",
    deprecated=True,
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
@router.get("/teams/{team_id}", deprecated=True)
def get_team(
    team_id: int, service: TeamServiceDep, league_id: int | None = None
) -> TeamPublic:
    """Retrieve one team from its league."""
    return service.get(team_id, league_id=league_id)


@router.put(
    "/leagues/{league_id}/teams/{team_id}", dependencies=[Depends(require_admin)]
)
@router.put("/teams/{team_id}", deprecated=True, dependencies=[Depends(require_admin)])
def update_team(
    team_id: int,
    data: TeamUpdate,
    service: TeamServiceDep,
    league_id: int | None = None,
) -> TeamPublic:
    """Update a team in its league."""
    return service.update(team_id, data, league_id=league_id)


@router.delete(
    "/leagues/{league_id}/teams/{team_id}",
    status_code=204,
    dependencies=[Depends(require_admin)],
)
@router.delete(
    "/teams/{team_id}",
    status_code=204,
    deprecated=True,
    dependencies=[Depends(require_admin)],
)
def delete_team(
    team_id: int, service: TeamServiceDep, league_id: int | None = None
) -> None:
    """Delete a team from its league."""
    service.delete(team_id, league_id=league_id)


@router.post(
    "/leagues/{league_id}/teams/{team_id}/image",
    dependencies=[Depends(require_admin)],
)
@router.post(
    "/teams/{team_id}/image",
    deprecated=True,
    dependencies=[Depends(require_admin)],
)
def upload_team_image(
    team_id: int,
    service: TeamServiceDep,
    league_id: int | None = None,
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
