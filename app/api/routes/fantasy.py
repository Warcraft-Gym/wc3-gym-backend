import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import (
    FantasyBetServiceDep,
    FantasyScoreServiceDep,
    FantasyTeamServiceDep,
    SeasonServiceDep,
    require_admin,
)
from app.core.exceptions import BadRequestError
from app.core.ordering import SortOrder
from app.core.query import QueryUtil
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
from app.services.fantasy_bets import BetSort

logger = logging.getLogger(__name__)

router = APIRouter(tags=["fantasy"])


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
    return service.create_fantasy_team(data)


@router.put(
    "/fantasy/teams/{team_id}",
    response_model=FantasyTeamPublic,
    dependencies=[Depends(require_admin)],
)
def update_team(
    team_id: int, data: FantasyTeamUpdate, service: FantasyTeamServiceDep
) -> FantasyTeamPublic:
    """Update an existing fantasy team."""
    return service.update_fantasy_team(team_id, data)


@router.delete(
    "/fantasy/teams/{team_id}", status_code=204, dependencies=[Depends(require_admin)]
)
def delete_team(team_id: int, service: FantasyTeamServiceDep) -> None:
    """Delete a team by its ID."""
    service.delete_fantasy_team(team_id)


@router.get("/fantasy/teams/{team_id}")
def get_team(team_id: int, service: FantasyTeamServiceDep) -> FantasyTeamPublic:
    """Retrieve a team by its ID."""
    return service.get_fantasy_team(team_id)


@router.post(
    "/fantasy/teams/addPlayers/{team_id}", dependencies=[Depends(require_admin)]
)
def addPlayers(
    team_id: int, data: FantasyTeamPlayerIds, service: FantasyTeamServiceDep
) -> FantasyTeamPublic:
    """Add players to a fantasy team for a season using their IDs."""
    return service.addFantasyPlayers(team_id, data.player_ids)


@router.post(
    "/fantasy/teams/removePlayers/{team_id}", dependencies=[Depends(require_admin)]
)
def removePlayers(
    team_id: int, data: FantasyTeamPlayerIds, service: FantasyTeamServiceDep
) -> FantasyTeamPublic:
    """Removes players from a fantasy team for a season using their IDs."""
    return service.removeFantasyPlayers(team_id, data.player_ids)


@router.get("/fantasy/teams")
def get_all_teams(
    service: FantasyTeamServiceDep,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[FantasyTeamPublic]:
    """Retrieve one page of fantasy teams, at most 500, ordered by id."""
    teams, total = service.getAll_fantasy_teams(limit=limit, offset=offset)
    response.headers["X-Total-Count"] = str(total)
    return teams or []


@router.post("/fantasy/teams/search")
def search_teams(
    service: FantasyTeamServiceDep,
    response: Response,
    query: str = "",
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[FantasyTeamPublic]:
    """Search teams by criteria, one page at a time, at most 500."""
    parsed = QueryUtil.parseQuery(query)
    if not parsed or not parsed.elementA:
        raise BadRequestError(f"No valid query found: {query}")
    teams, total = service.search_fantasy_teams(parsed, limit=limit, offset=offset)
    if total is not None:
        response.headers["X-Total-Count"] = str(total)
    return teams or []


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
    service.delete_fantasy_bet(bet_id)


@router.get("/fantasy/bets/{bet_id}")
def get_bet(bet_id: int, service: FantasyBetServiceDep) -> FantasyBetPublic:
    """Retrieve a bet by its ID."""
    return service.get_fantasy_bet(bet_id)


@router.get("/fantasy/bets")
def get_all_bets(
    service: FantasyBetServiceDep,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[FantasyBetPublic]:
    """Retrieve one page of fantasy bets, at most 500."""
    bets, total = service.getAll_fantasy_bets(limit=limit, offset=offset)
    if total is not None:
        response.headers["X-Total-Count"] = str(total)
    return bets or []


@router.post("/fantasy/bets/search")
def search_bets(
    service: FantasyBetServiceDep,
    response: Response,
    query: str = "",
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
    sort: BetSort | None = None,
    order: SortOrder = "asc",
) -> list[FantasyBetPublic]:
    """Search bets by criteria, one page at a time, at most 500.

    sort names the field the page is ordered by, and the bet id breaks its ties.
    """
    parsed = QueryUtil.parseQuery(query)
    if not parsed or not parsed.elementA:
        raise BadRequestError(f"No valid query found: {query}")
    bets, total = service.search_fantasy_bets(
        parsed, limit=limit, offset=offset, sort=sort, order=order
    )
    if total is not None:
        response.headers["X-Total-Count"] = str(total)
    return bets or []


@router.get("/fantasy/teams/{team_id}/season/{season_id}/breakdown")
def get_fantasy_team_breakdown(
    team_id: int,
    season_id: int,
    season_service: SeasonServiceDep,
    fantasy_score_service: FantasyScoreServiceDep,
) -> FantasyTeamScoreBreakdown:
    """Get detailed score breakdown for a fantasy team.

    Returns a detailed breakdown showing how each component of the fantasy
    team score was calculated.
    """
    # get_season raises NotFoundError, which answers 404
    season = season_service.get_season(season_id)
    return fantasy_score_service.getTeamScoreBreakdown(team_id, season)
