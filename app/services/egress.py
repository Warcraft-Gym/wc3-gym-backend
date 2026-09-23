"""The daily egress ledger: what each route costs the database."""

from datetime import timedelta

from sqlalchemy.dialects import postgresql, sqlite
from sqlmodel import col, select

from app.core.db import Cost, Session
from app.models.egress_ledger import EgressLedger
from app.models.types import utcnow


def record(route: str, method: str, cost: Cost, size: int) -> None:
    """Add one call of this route to today's row, in one upsert statement."""
    values = {
        "day": utcnow().date(),
        "route": route,
        "method": method,
        "calls": 1,
        "statements": cost.statements,
        "rows": cost.rows,
        "bytes": size,
    }
    with Session.begin() as session:
        dialect = session.get_bind().dialect.name
        insert = postgresql.insert if dialect == "postgresql" else sqlite.insert
        statement = insert(EgressLedger).values(values)
        session.execute(
            statement.on_conflict_do_update(
                index_elements=["day", "route", "method"],
                set_={
                    name: col(getattr(EgressLedger, name)) + statement.excluded[name]
                    for name in ("calls", "statements", "rows", "bytes")
                },
            )
        )


def recent(days: int) -> list[EgressLedger]:
    """The rows of the last `days` days, today included, most rows first."""
    since = utcnow().date() - timedelta(days=days - 1)
    with Session() as session:
        return list(
            session.scalars(
                select(EgressLedger)
                .where(col(EgressLedger.day) >= since)
                .order_by(col(EgressLedger.rows).desc(), col(EgressLedger.route))
            ).all()
        )
