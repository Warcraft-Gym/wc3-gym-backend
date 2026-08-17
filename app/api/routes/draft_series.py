import logging

from fastapi import APIRouter, Depends

from app.api.deps import DraftSeriesServiceDep, SeriesServiceDep, require_admin
from app.models.draft_series import (
    DraftSeriesCreate,
    DraftSeriesPublic,
    DraftSeriesUpdate,
)
from app.models.series import SeriesPublic

logger = logging.getLogger(__name__)

router = APIRouter(tags=["draft-series"])


@router.post(
    "/draft-series",
    status_code=201,
    response_model=DraftSeriesPublic,
    dependencies=[Depends(require_admin)],
)
def add_draft_series(
    data: DraftSeriesCreate, service: DraftSeriesServiceDep
) -> DraftSeriesPublic:
    """Create a new draft series (visible in admin UI only)"""
    return service.create_draft_series(data)


@router.put(
    "/draft-series/{draft_series_id}",
    response_model=DraftSeriesPublic,
    dependencies=[Depends(require_admin)],
)
def update_draft_series(
    draft_series_id: int,
    data: DraftSeriesUpdate,
    service: DraftSeriesServiceDep,
) -> DraftSeriesPublic:
    """Update the data of an existing draft series"""
    return service.update_draft_series(draft_series_id, data)


@router.delete(
    "/draft-series/{draft_series_id}",
    status_code=204,
    dependencies=[Depends(require_admin)],
)
def delete_draft_series(draft_series_id: int, service: DraftSeriesServiceDep) -> None:
    """Delete a draft series by its ID."""
    service.delete_draft_series(draft_series_id)


@router.get("/draft-series/{draft_series_id}")
def get_draft_series(
    draft_series_id: int, service: DraftSeriesServiceDep
) -> DraftSeriesPublic:
    """Retrieve a draft series by its ID."""
    return service.get_draft_series(draft_series_id)


@router.get("/draft-series/match/{match_id}")
def get_draft_series_by_match(
    match_id: int, service: DraftSeriesServiceDep
) -> list[DraftSeriesPublic]:
    """Return all draft series for a specific match"""
    return service.get_draft_series_by_match(match_id) or []


@router.delete(
    "/draft-series/match/{match_id}",
    status_code=204,
    dependencies=[Depends(require_admin)],
)
def delete_all_draft_series_for_match(
    match_id: int, service: DraftSeriesServiceDep
) -> None:
    """Delete all draft series for a specific match"""
    service.delete_all_drafts_for_match(match_id)


@router.post(
    "/draft-series/{draft_series_id}/promote",
    status_code=201,
    dependencies=[Depends(require_admin)],
)
def promote_draft_series(
    draft_series_id: int,
    service: DraftSeriesServiceDep,
    series_service: SeriesServiceDep,
) -> SeriesPublic:
    """Convert a draft series to a real published series and delete the draft"""
    # Get the draft series
    draft_series = service.get_draft_series(draft_series_id)

    # Convert to a SeriesCreate
    series_create = service.convert_to_series(draft_series)

    # Create as real series (this will trigger all calculations)
    created_series = series_service.create_series(series_create)

    # Delete the draft
    service.delete_draft_series(draft_series_id)

    return created_series
