from fastapi import APIRouter, Response

from app.api.deps import edge_cache
from app.models.home import HomeSeries
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
    # series are booked and claimed through the day
    edge_cache(response, 120, tags=("home",))
    return home.series()
