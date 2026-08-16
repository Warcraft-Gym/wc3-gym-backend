"""A probe target: the route answers only when the database answers.

The check has no entity and no business rule, so it opens the session
factory itself instead of going through a service. A database failure
propagates as the SQLAlchemyError it is; the handler in app.main answers
with the fixed 500 body.
"""

from fastapi import APIRouter
from sqlalchemy import text

from app.core.db import Session

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Report that the application reaches the database."""
    with Session() as session:
        session.execute(text("SELECT 1"))
    return {"status": "ok"}
