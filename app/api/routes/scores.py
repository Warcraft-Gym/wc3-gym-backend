import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.deps import (
    MatchServiceDep,
    ScoreServiceDep,
    SeasonServiceDep,
    SeriesServiceDep,
    require_admin,
)
from app.exceptions import NotFoundException
from app.utils.query_util import QueryUtil

logger = logging.getLogger(__name__)

router = APIRouter(tags=["score"])

# Global dictionary to track calculation progress per season
calculation_progress = {}


@router.get("/season/{season_id}/calculate/status")
def get_calc_status(season_id: int):
    """Get the current calculation progress for a season"""
    progress = calculation_progress.get(season_id)

    if not progress:
        return {
            "status": "idle",
            "progress": 0,
            "total": 0,
            "current": 0,
            "message": "No calculation in progress",
        }

    return progress


@router.post("/season/{season_id}/calculate/", dependencies=[Depends(require_admin)])
def calc_score(
    season_id: int,
    season_service: SeasonServiceDep,
    match_service: MatchServiceDep,
    series_service: SeriesServiceDep,
    score_service: ScoreServiceDep,
):
    """Calculate the scores of a given season.

    Calculates series, match and team scores for the given season. This is a
    long-running synchronous operation that updates progress tracking.
    """
    # Check if calculation is already in progress for this season
    if (
        season_id in calculation_progress
        and calculation_progress[season_id]["status"] == "running"
    ):
        return JSONResponse(
            {
                "error": "Calculation already in progress for this season",
                "progress": calculation_progress[season_id],
            },
            status_code=409,
        )

    # Initialize progress tracking
    calculation_progress[season_id] = {
        "status": "running",
        "progress": 0,
        "total": 0,
        "current": 0,
        "message": "Starting calculation...",
    }

    # Perform calculation synchronously
    result = perform_calculation(
        season_id, season_service, match_service, series_service, score_service
    )
    return JSONResponse(result, status_code=200)


def perform_calculation(
    season_id: int, season_service, match_service, series_service, score_service
):
    """Perform the actual score calculation with progress tracking"""
    try:
        teams = {}
        season = season_service.get_season(season_id)
        if season:
            season = season.to_dict()

        query = QueryUtil.parseQuery("season_id == " + str(season["id"]))
        matches = match_service.search(query)

        total_matches = len(matches)

        # Update progress - initialization complete
        calculation_progress[season_id]["total"] = total_matches
        calculation_progress[season_id]["message"] = (
            f"Processing {total_matches} matches..."
        )

        for index, match in enumerate(matches):
            # Update progress for current match
            calculation_progress[season_id]["current"] = index + 1
            calculation_progress[season_id]["progress"] = int(
                ((index + 1) / total_matches) * 100
            )
            calculation_progress[season_id]["message"] = (
                f"Processing match {index + 1} of {total_matches}"
            )

            query = QueryUtil.parseQuery("match_id == " + str(match.id))
            series = series_service.search(query)
            team1_points = 0
            team2_points = 0

            for singleSeries in series:
                try:
                    if (
                        singleSeries.player1_score == None
                        or singleSeries.player2_score == None
                    ):
                        continue
                    calculatedSeries = score_service.calculateSeriesScore(singleSeries)
                except Exception as e:
                    raise Exception(
                        str(e) + " for series with id " + str(singleSeries.id)
                    )

                series_service.update_series(calculatedSeries.id, calculatedSeries)
                team1_points += calculatedSeries.player1_points
                team2_points += calculatedSeries.player2_points

            match.team1_score = team1_points
            match.team2_score = team2_points

            teams[match.team1.id] = match.team1
            teams[match.team2.id] = match.team2

            match_service.update_match(match.id, match)

        # Update team scores
        calculation_progress[season_id]["message"] = "Updating team standings..."
        for team in teams.values():
            score_service.updateTeamScore(team, season_id)

        # Mark as complete
        calculation_progress[season_id]["status"] = "completed"
        calculation_progress[season_id]["progress"] = 100
        calculation_progress[season_id]["message"] = (
            "Calculation completed successfully"
        )

        return season

    except NotFoundException as e:
        logger.error(f"Season not found: {e}")
        calculation_progress[season_id]["status"] = "error"
        calculation_progress[season_id]["message"] = f"Error: {e!s}"
        raise
    except Exception as e:
        logger.error(f"Error calculating scores: {e}")
        calculation_progress[season_id]["status"] = "error"
        calculation_progress[season_id]["message"] = f"Error: {e!s}"
        raise
