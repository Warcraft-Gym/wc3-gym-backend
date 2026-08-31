"""The parsed query every /search route takes, as one dependency."""

from typing import Annotated

from fastapi import Depends

from app.core.exceptions import BadRequestError
from app.core.query import QueryElement, QueryUtil


def parse_query(query: str = "") -> QueryElement:
    """The caller's search query, parsed. A query the parser rejects answers 400."""
    parsed = QueryUtil.parse_query(query)
    if not parsed or not parsed.elementA:
        raise BadRequestError(f"No valid query found: {query}")
    return parsed


SearchQuery = Annotated[QueryElement, Depends(parse_query)]
