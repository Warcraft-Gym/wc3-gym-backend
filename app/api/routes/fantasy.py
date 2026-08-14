import logging
from typing import Annotated

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from app.api.deps import (
    FantasyBetServiceDep,
    FantasyScoreServiceDep,
    FantasyTeamServiceDep,
    SeasonServiceDep,
    require_admin,
)
from app.schemas.fantasy_bet import FantasyBet
from app.schemas.fantasy_team import FantasyTeam
from app.utils.query_util import QueryUtil

logger = logging.getLogger(__name__)

router = APIRouter(tags=["fantasy"])


# Team endpoints
@router.post("/fantasy/teams", status_code=201, dependencies=[Depends(require_admin)])
def add_fantasy_team(data: Annotated[dict, Body()], service: FantasyTeamServiceDep):
    """Create a new fantasy team with the provided name."""
    team = service.create_fantasy_team(FantasyTeam(data))
    return team.to_dict() if team else None


@router.put("/fantasy/teams/{team_id}", dependencies=[Depends(require_admin)])
def update_team(
    team_id: int, data: Annotated[dict, Body()], service: FantasyTeamServiceDep
):
    """Update an existing fantasy team."""
    team = service.update_fantasy_team(team_id, FantasyTeam(data))
    return team.to_dict() if team else None


@router.delete(
    "/fantasy/teams/{team_id}", status_code=204, dependencies=[Depends(require_admin)]
)
def delete_team(team_id: int, service: FantasyTeamServiceDep):
    """Delete a team by its ID."""
    service.delete_fantasy_team(team_id)


@router.get("/fantasy/teams/{team_id}")
def get_team(team_id: int, service: FantasyTeamServiceDep):
    """Retrieve a team by its ID."""
    team = service.get_fantasy_team(team_id)
    return team.to_dict() if team else None


@router.post(
    "/fantasy/teams/addPlayers/{team_id}", dependencies=[Depends(require_admin)]
)
def addPlayers(
    team_id: int, data: Annotated[dict, Body()], service: FantasyTeamServiceDep
):
    """Add players to a fantasy team for a season using their IDs."""
    team = service.addFantasyPlayers(team_id, data.get("player_ids"))
    return team.to_dict() if team else None


@router.post(
    "/fantasy/teams/removePlayers/{team_id}", dependencies=[Depends(require_admin)]
)
def removePlayers(
    team_id: int, data: Annotated[dict, Body()], service: FantasyTeamServiceDep
):
    """Removes players from a fantasy team for a season using their IDs."""
    team = service.removeFantasyPlayers(team_id, data.get("player_ids"))
    return team.to_dict() if team else None


@router.get("/fantasy/teams")
def get_all_teams(service: FantasyTeamServiceDep):
    """Retrieve all fantasy teams."""
    return [team.to_dict() for team in service.getAll_fantasy_teams() or []]


@router.post("/fantasy/teams/search")
def search_teams(service: FantasyTeamServiceDep, query: str = ""):
    """Search teams by criteria using a custom query format."""
    parsed = QueryUtil.parseQuery(query)
    if not parsed or not parsed.elementA:
        raise Exception(f"No valid query found: {query}")
    return [team.to_dict() for team in service.search_fantasy_teams(parsed) or []]


# Bet endpoints
@router.post("/fantasy/bets", status_code=201, dependencies=[Depends(require_admin)])
def add_fantasy_bet(data: Annotated[dict, Body()], service: FantasyBetServiceDep):
    """Create a new fantasy bet with the provided name."""
    try:
        bet = service.create_fantasy_bet(FantasyBet(data))
        return bet.to_dict() if bet else None
    except ValueError as e:
        logger.error(f"Validation error: {e}")
        return JSONResponse({"error": str(e)}, status_code=400)


@router.put("/fantasy/bets/{bet_id}", dependencies=[Depends(require_admin)])
def update_bet(
    bet_id: int, data: Annotated[dict, Body()], service: FantasyBetServiceDep
):
    """Update an existing fantasy bet."""
    try:
        bet = service.update_fantasy_bet(bet_id, FantasyBet(data))
        return bet.to_dict() if bet else None
    except ValueError as e:
        logger.error(f"Validation error: {e}")
        return JSONResponse({"error": str(e)}, status_code=400)


@router.delete(
    "/fantasy/bets/{bet_id}", status_code=204, dependencies=[Depends(require_admin)]
)
def delete_bet(bet_id: int, service: FantasyBetServiceDep):
    """Delete a bet by its ID."""
    service.delete_fantasy_bet(bet_id)


@router.get("/fantasy/bets/{bet_id}")
def get_bet(bet_id: int, service: FantasyBetServiceDep):
    """Retrieve a bet by its ID."""
    bet = service.get_fantasy_bet(bet_id)
    return bet.to_dict() if bet else None


@router.get("/fantasy/bets")
def get_all_bets(service: FantasyBetServiceDep):
    """Retrieve all fantasy bets."""
    return [bet.to_dict() for bet in service.getAll_fantasy_bets() or []]


@router.post("/fantasy/bets/search")
def search_bets(service: FantasyBetServiceDep, query: str = ""):
    """Search bets by criteria using a custom query format."""
    parsed = QueryUtil.parseQuery(query)
    if not parsed or not parsed.elementA:
        raise Exception(f"No valid query found: {query}")
    return [bet.to_dict() for bet in service.search_fantasy_bets(parsed) or []]


@router.get("/fantasy/teams/{team_id}/season/{season_id}/breakdown")
def get_fantasy_team_breakdown(
    team_id: int,
    season_id: int,
    season_service: SeasonServiceDep,
    fantasy_score_service: FantasyScoreServiceDep,
):
    """Get detailed score breakdown for a fantasy team.

    Returns a detailed breakdown showing how each component of the fantasy
    team score was calculated.
    """
    season = season_service.get_season(season_id)
    if not season:
        return JSONResponse(
            {"error": f"Season with id {season_id} not found"}, status_code=404
        )

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
):
    """Calculate the fantasy scores of a given season."""
    season = season_service.get_season(season_id)
    fantasy_score_service.calculateTeamScores(season)
