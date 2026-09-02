import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import PositiveInt

from app.api.deps import (
    Credentials,
    FantasyBetServiceDep,
    FantasyTeamServiceDep,
    SeasonServiceDep,
    UserServiceDep,
    require_admin,
    require_login,
)
from app.api.search import SearchQuery
from app.core.exceptions import ApiError
from app.core.ordering import SortOrder
from app.models.fantasy_bet import (
    FantasyBetCreate,
    FantasyBetPublic,
    FantasyBetUpdate,
)
from app.models.fantasy_score import FantasyTeamScoreBreakdown
from app.models.fantasy_team import (
    FantasyTeamCreate,
    FantasyTeamPlayerIds,
    FantasyTeamPublic,
    FantasyTeamUpdate,
)
from app.services import discord_roles
from app.services.fantasy_bets import BetSort
from app.services.fantasy_scores import team_score_breakdown

logger = logging.getLogger(__name__)

router = APIRouter(tags=["fantasy"])


def require_admin_or_owner(
    team_id: int,
    request: Request,
    credentials: Credentials,
    service: FantasyTeamServiceDep,
    users: UserServiceDep,
) -> bool:
    """Admit an admin (True) or the member who owns the fantasy team (False)."""
    claims = require_login(request, credentials)
    if claims.get("role") == "admin" or claims["sub"] == "admin":
        return True
    rows = users.find_by_discord_id(claims["sub"])
    if (
        claims.get("role") != "guest"
        and rows
        and service.get(team_id).captain_id == rows[0].id
    ):
        return False
    raise ApiError(403, {"error": "Admins or the fantasy team's owner only"})


@router.put("/fantasy/tiers", status_code=204, dependencies=[Depends(require_admin)])
def set_fantasy_tiers(
    tiers: dict[int, PositiveInt],
    service: UserServiceDep,
    season_id: int | None = None,
) -> None:
    """Replace one season's tier allocation in one transaction, unlisted players lose theirs."""
    season = season_id or discord_roles.current_season()
    if season is None:
        raise ApiError(404, {"error": "No season to allocate tiers for"})
    service.set_fantasy_tiers(season, tiers)


# Team endpoints
@router.post(
    "/fantasy/teams",
    status_code=201,
    response_model=FantasyTeamPublic,
    dependencies=[Depends(require_admin)],
)
def add_fantasy_team(
    data: FantasyTeamCreate, service: FantasyTeamServiceDep
) -> FantasyTeamPublic:
    """Create a new fantasy team with the provided name."""
    return service.add(data)


@router.put(
    "/fantasy/teams/{team_id}",
    response_model=FantasyTeamPublic,
)
def update_team(
    team_id: int,
    data: FantasyTeamUpdate,
    service: FantasyTeamServiceDep,
    is_admin: Annotated[bool, Depends(require_admin_or_owner)],
) -> FantasyTeamPublic:
    """Update an existing fantasy team. The owner edits it, an admin reseats it."""
    if not is_admin:
        current = service.get(team_id)
        changed = data.model_dump(exclude_unset=True)
        for field in ("captain_id", "season_id"):
            if field in changed and changed[field] != getattr(current, field):
                raise ApiError(
                    403, {"error": "Only admins reassign the owner or season"}
                )
    return service.update(team_id, data)


@router.delete(
    "/fantasy/teams/{team_id}", status_code=204, dependencies=[Depends(require_admin)]
)
def delete_team(team_id: int, service: FantasyTeamServiceDep) -> None:
    """Delete a team by its ID."""
    service.delete(team_id)


@router.get("/fantasy/teams/{team_id}")
def get_team(team_id: int, service: FantasyTeamServiceDep) -> FantasyTeamPublic:
    """Retrieve a team by its ID."""
    return service.get(team_id)


@router.post(
    "/fantasy/teams/{team_id}/players",
    dependencies=[Depends(require_admin_or_owner)],
)
def add_players(
    team_id: int, data: FantasyTeamPlayerIds, service: FantasyTeamServiceDep
) -> FantasyTeamPublic:
    """Add players to a fantasy team for a season using their IDs."""
    return service.add_players(team_id, data.player_ids)


@router.delete(
    "/fantasy/teams/{team_id}/players",
    dependencies=[Depends(require_admin_or_owner)],
)
def remove_players(
    team_id: int, data: FantasyTeamPlayerIds, service: FantasyTeamServiceDep
) -> FantasyTeamPublic:
    """Removes players from a fantasy team for a season using their IDs."""
    return service.remove_players(team_id, data.player_ids)


@router.get("/fantasy/teams")
def get_all_teams(
    service: FantasyTeamServiceDep,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[FantasyTeamPublic]:
    """Retrieve one page of fantasy teams, at most 500, ordered by id."""
    teams, total = service.get_all(limit=limit, offset=offset)
    response.headers["X-Total-Count"] = str(total)
    return teams


@router.post("/fantasy/teams/search")
def search_teams(
    service: FantasyTeamServiceDep,
    response: Response,
    query: SearchQuery,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[FantasyTeamPublic]:
    """Search teams by criteria, one page at a time, at most 500."""
    teams, total = service.search(query, limit=limit, offset=offset)
    if total is not None:
        response.headers["X-Total-Count"] = str(total)
    return teams


# Bet endpoints
@router.post(
    "/fantasy/bets",
    status_code=201,
    dependencies=[Depends(require_admin)],
)
def add_fantasy_bet(
    data: FantasyBetCreate, service: FantasyBetServiceDep
) -> FantasyBetPublic:
    """Create a new fantasy bet with the provided name."""
    return service.create_fantasy_bet(data)


@router.put(
    "/fantasy/bets/{bet_id}",
    dependencies=[Depends(require_admin)],
)
def update_bet(
    bet_id: int, data: FantasyBetUpdate, service: FantasyBetServiceDep
) -> FantasyBetPublic:
    """Update an existing fantasy bet."""
    return service.update_fantasy_bet(bet_id, data)


@router.delete(
    "/fantasy/bets/{bet_id}", status_code=204, dependencies=[Depends(require_admin)]
)
def delete_bet(bet_id: int, service: FantasyBetServiceDep) -> None:
    """Delete a bet by its ID."""
    service.delete(bet_id)


@router.get("/fantasy/bets/{bet_id}")
def get_bet(bet_id: int, service: FantasyBetServiceDep) -> FantasyBetPublic:
    """Retrieve a bet by its ID."""
    return service.get(bet_id)


@router.get("/fantasy/bets")
def get_all_bets(
    service: FantasyBetServiceDep,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[FantasyBetPublic]:
    """Retrieve one page of fantasy bets, at most 500."""
    bets, total = service.get_all(limit=limit, offset=offset)
    if total is not None:
        response.headers["X-Total-Count"] = str(total)
    return bets


@router.post("/fantasy/bets/search")
def search_bets(
    service: FantasyBetServiceDep,
    response: Response,
    query: SearchQuery,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
    sort: BetSort | None = None,
    order: SortOrder = "asc",
) -> list[FantasyBetPublic]:
    """Search bets by criteria, one page at a time, at most 500.

    sort names the field the page is ordered by, and the bet id breaks its ties.
    """
    bets, total = service.search(
        query, limit=limit, offset=offset, sort=sort, order=order
    )
    if total is not None:
        response.headers["X-Total-Count"] = str(total)
    return bets


@router.get(
    "/fantasy/teams/{team_id}/season/{season_id}/breakdown",
    response_model=FantasyTeamScoreBreakdown,
)
def get_fantasy_team_breakdown(
    team_id: int,
    season_id: int,
    season_service: SeasonServiceDep,
    fantasy_team_service: FantasyTeamServiceDep,
    fantasy_bet_service: FantasyBetServiceDep,
) -> dict[str, Any]:
    """Get detailed score breakdown for a fantasy team.

    Returns a detailed breakdown showing how each component of the fantasy
    team score was calculated.
    """
    # get raises NotFoundError, which answers 404
    season = season_service.get(season_id)
    return team_score_breakdown(
        fantasy_team_service, fantasy_bet_service, team_id, season
    )
