import logging
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.deps import (
    FantasyBetServiceDep,
    FantasyScoreServiceDep,
    FantasyTeamServiceDep,
    SeasonServiceDep,
    require_admin,
)
from app.models.fantasy_bet import (
    FantasyBetCreate,
    FantasyBetPublic,
    FantasyBetUpdate,
)
from app.models.fantasy_team import (
    FantasyTeamCreate,
    FantasyTeamPlayerIds,
    FantasyTeamPublic,
    FantasyTeamUpdate,
)
from app.utils.query_util import QueryUtil

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
def get_all_teams(service: FantasyTeamServiceDep) -> list[FantasyTeamPublic]:
    """Retrieve all fantasy teams."""
    return service.getAll_fantasy_teams() or []


@router.post("/fantasy/teams/search")
def search_teams(
    service: FantasyTeamServiceDep, query: str = ""
) -> list[FantasyTeamPublic]:
    """Search teams by criteria using a custom query format."""
    parsed = QueryUtil.parseQuery(query)
    if not parsed or not parsed.elementA:
        raise Exception(f"No valid query found: {query}")
    return service.search_fantasy_teams(parsed) or []


# Bet endpoints
@router.post(
    "/fantasy/bets",
    status_code=201,
    response_model=FantasyBetPublic,
    dependencies=[Depends(require_admin)],
)
def add_fantasy_bet(
    data: FantasyBetCreate, service: FantasyBetServiceDep
) -> JSONResponse | FantasyBetPublic | None:
    """Create a new fantasy bet with the provided name."""
    try:
        return service.create_fantasy_bet(data)
    except ValueError as e:
        logger.error(f"Validation error: {e}")
        return JSONResponse({"error": str(e)}, status_code=400)


@router.put(
    "/fantasy/bets/{bet_id}",
    response_model=FantasyBetPublic,
    dependencies=[Depends(require_admin)],
)
def update_bet(
    bet_id: int, data: FantasyBetUpdate, service: FantasyBetServiceDep
) -> JSONResponse | FantasyBetPublic | None:
    """Update an existing fantasy bet."""
    try:
        return service.update_fantasy_bet(bet_id, data)
    except ValueError as e:
        logger.error(f"Validation error: {e}")
        return JSONResponse({"error": str(e)}, status_code=400)


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
def get_all_bets(service: FantasyBetServiceDep) -> list[FantasyBetPublic]:
    """Retrieve all fantasy bets."""
    return service.getAll_fantasy_bets() or []


@router.post("/fantasy/bets/search")
def search_bets(
    service: FantasyBetServiceDep, query: str = ""
) -> list[FantasyBetPublic]:
    """Search bets by criteria using a custom query format."""
    parsed = QueryUtil.parseQuery(query)
    if not parsed or not parsed.elementA:
        raise Exception(f"No valid query found: {query}")
    return service.search_fantasy_bets(parsed) or []


@router.get("/fantasy/teams/{team_id}/season/{season_id}/breakdown")
def get_fantasy_team_breakdown(
    team_id: int,
    season_id: int,
    season_service: SeasonServiceDep,
    fantasy_score_service: FantasyScoreServiceDep,
) -> dict[str, Any]:
    """Get detailed score breakdown for a fantasy team.

    Returns a detailed breakdown showing how each component of the fantasy
    team score was calculated.
    """
    # get_season raises NotFoundError for an unknown id, so a missing
    # season already answers 404.
    season = season_service.get_season(season_id)
    return fantasy_score_service.getTeamScoreBreakdown(team_id, season)


@router.post(
    "/fantasy/season/{season_id}/calculate/",
    status_code=204,
    dependencies=[Depends(require_admin)],
)
def calc_fantasy_score(
    season_id: int,
    season_service: SeasonServiceDep,
    fantasy_score_service: FantasyScoreServiceDep,
) -> None:
    """Calculate the fantasy scores of a given season."""
    season = season_service.get_season(season_id)
    fantasy_score_service.calculateTeamScores(season)
