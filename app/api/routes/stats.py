import csv
import io
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, File, Query, Response, UploadFile

from app.api.deps import StatsServiceDep, require_admin
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.ordering import SortOrder
from app.models.player_career_stats import (
    PlayerCareerStatsUpdate,
)
from app.services.derived import CareerSort

logger = logging.getLogger(__name__)

router = APIRouter(tags=["stats"])


@router.get("/stats/career")
def get_all_career_stats(
    service: StatsServiceDep,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
    search: str = "",
    sort: CareerSort | None = None,
    order: SortOrder = "asc",
) -> list[dict[str, Any]]:
    """Retrieve one page of career statistics, at most 500, ordered by rating.

    search keeps the rows whose player name or user name holds it, without
    case. The header counts the kept rows.

    sort names the field the rows are ordered by, and the id breaks its ties.
    """
    stats, total = service.get_all(
        limit=limit, offset=offset, search=search, sort=sort, order=order
    )
    response.headers["X-Total-Count"] = str(total)
    return [stat.to_dict() for stat in stats]


@router.get("/stats/career/{stat_id}")
def get_career_stats_by_user(stat_id: int, service: StatsServiceDep) -> dict[str, Any]:
    """Retrieve career statistics for a single player by user ID."""
    stat = service.get_by_user_id(stat_id)
    if not stat:
        raise NotFoundError("Stats not found")
    return stat.to_dict()


@router.put("/stats/career/{stat_id}", dependencies=[Depends(require_admin)])
def update_career_stats(
    stat_id: int, data: Annotated[dict, Body()], service: StatsServiceDep
) -> dict[str, Any]:
    """Update historical baseline values and user link for career stats."""
    update = PlayerCareerStatsUpdate(**data)
    stat = service.update_career_stats(stat_id, update)
    if not stat:
        raise NotFoundError("Stats not found")
    return stat.to_dict()


@router.delete("/stats/career/{stat_id}", dependencies=[Depends(require_admin)])
def delete_career_stats(stat_id: int, service: StatsServiceDep) -> dict[str, Any]:
    """Delete career statistics record."""
    success = service.delete_career_stats(stat_id)
    if not success:
        raise NotFoundError("Stats not found")
    return {"success": True}


@router.post("/stats/career/import-csv", dependencies=[Depends(require_admin)])
def import_historical_csv(
    service: StatsServiceDep, file: Annotated[UploadFile | None, File()] = None
) -> dict[str, Any]:
    """One-time import of historical stats.

    Requires CSV file upload with columns: NAME, RATING, WON Series, LOST
    Series, WON Games, LOST Games, Seasons PLAYED
    """
    if file is None:
        raise BadRequestError("No file provided")

    if file.filename == "":
        raise BadRequestError("No file selected")

    if not file.filename.endswith(".csv"):
        raise BadRequestError("File must be a CSV")

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

    return {
        "success": True,
        "imported": result["imported"],
        "skipped": result["skipped"],
        "errors": result["errors"],
    }
