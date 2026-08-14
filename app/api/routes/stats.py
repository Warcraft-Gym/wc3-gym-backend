import csv
import io
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, File, UploadFile
from fastapi.responses import JSONResponse

from app.api.deps import StatsServiceDep, require_admin
from app.models.player_career_stats import (
    PlayerCareerStatsUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["stats"])


@router.get("/stats/career")
def get_all_career_stats(service: StatsServiceDep) -> list[dict[str, Any]]:
    """Retrieve career statistics for all players, ordered by rating."""
    return [stat.to_dict() for stat in service.get_all_career_stats() or []]


@router.get("/stats/career/{stat_id}")
def get_career_stats_by_user(stat_id: int, service: StatsServiceDep) -> JSONResponse:
    """Retrieve career statistics for a single player by user ID."""
    stat = service.get_career_stats_by_user(stat_id)
    if stat:
        return JSONResponse(stat.to_dict(), status_code=200)
    return JSONResponse({"error": "Stats not found"}, status_code=404)


@router.put("/stats/career/{stat_id}", dependencies=[Depends(require_admin)])
def update_career_stats(
    stat_id: int, data: Annotated[dict, Body()], service: StatsServiceDep
) -> JSONResponse:
    """Update historical baseline values and user link for career stats."""
    stat_dto = PlayerCareerStatsUpdate(**data)
    stat = service.update_career_stats(stat_id, stat_dto)
    if stat:
        return JSONResponse(stat.to_dict(), status_code=200)
    return JSONResponse({"error": "Stats not found"}, status_code=404)


@router.delete("/stats/career/{stat_id}", dependencies=[Depends(require_admin)])
def delete_career_stats(stat_id: int, service: StatsServiceDep) -> JSONResponse:
    """Delete career statistics record."""
    success = service.delete_career_stats(stat_id)
    if success:
        return JSONResponse({"success": True}, status_code=200)
    return JSONResponse({"error": "Stats not found"}, status_code=404)


@router.post("/stats/career/import-csv", dependencies=[Depends(require_admin)])
def import_historical_csv(
    service: StatsServiceDep, file: Annotated[UploadFile | None, File()] = None
) -> JSONResponse:
    """One-time import of historical stats.

    Requires CSV file upload with columns: NAME, RATING, WON Series, LOST
    Series, WINRATE (x2), WON Games, LOST Games, Seasons PLAYED, AVG NUM
    Series
    """
    if file is None:
        return JSONResponse({"error": "No file provided"}, status_code=400)

    if file.filename == "":
        return JSONResponse({"error": "No file selected"}, status_code=400)

    if not file.filename.endswith(".csv"):
        return JSONResponse({"error": "File must be a CSV"}, status_code=400)

    # Read CSV content with flexible encoding (handles Windows files)
    try:
        # Try UTF-8 first
        stream = io.StringIO(file.file.read().decode("UTF-8"), newline=None)
    except UnicodeDecodeError:
        # Fallback to Windows-1252 encoding
        file.file.seek(0)
        stream = io.StringIO(file.file.read().decode("Windows-1252"), newline=None)

    csv_input = csv.DictReader(stream)

    result = service.import_historical_stats(csv_input)

    return JSONResponse(
        {
            "success": True,
            "imported": result["imported"],
            "skipped": result["skipped"],
            "errors": result["errors"],
        },
        status_code=200,
    )


@router.post("/stats/career/recalculate", dependencies=[Depends(require_admin)])
def recalculate_stats(service: StatsServiceDep) -> dict[str, Any]:
    """Combines historical baseline with ALL series data in the database to
    update player stats. Always uses complete series history for accurate
    career totals. Run this after importing data or to refresh stats.
    """
    result = service.recalculate_all_stats()

    return {"success": True, "updated": result["updated"], "errors": result["errors"]}
