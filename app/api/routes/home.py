from fastapi import APIRouter, Response

from app.api.deps import edge_cache
from app.models.home import HomeSeries, UpcomingSeriesRow
from app.services import home

router = APIRouter(tags=["home"])


# The answer rides on every visit to the home page, so an empty field is left out
@router.get("/home/series", response_model_exclude_none=True)
def get_home_series(response: Response) -> HomeSeries:
    """The next booked series of every event kind, and the casted series.

    Three lists in one answer: `next`, `casts_upcoming` and `casts_recent`.
    They hold published events only and no draft pairing. A field with no
    value is left out of the row, so a reader treats a missing key as null.
    """
    edge_cache(response, "running")  # series are booked and claimed through the day
    return home.series()


# Read from the hub's "All upcoming"; an empty field is left out, as on the hub
@router.get("/home/series/upcoming", response_model_exclude_none=True)
def get_upcoming_series(response: Response) -> list[UpcomingSeriesRow]:
    """Every booked series still to play, of every event kind, in time order.

    The hub row of each, with every claim on it in `casts`, so a caster claims
    a series from the list. Published events only, no draft pairing, at most
    100 rows.
    """
    edge_cache(response, "running")  # series are booked and claimed through the day
    return home.upcoming()
