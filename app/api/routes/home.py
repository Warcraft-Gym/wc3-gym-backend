from fastapi import APIRouter, Response

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
    # series are booked and claimed through the day; the edge serves one read for two minutes
    response.headers["Cache-Control"] = "public, s-maxage=120"
    # the edge keeps the headers of the request that filled it, and CORSMiddleware
    # writes none when that request has no Origin, so a browser reads a copy it blocks
    response.headers["Access-Control-Allow-Origin"] = "*"
    return home.series()
