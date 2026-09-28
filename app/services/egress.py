"""The daily egress ledger: what each route costs the database."""

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session as OrmSession
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
        "db_bytes": cost.db_bytes,
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
                    for name in ("calls", "statements", "rows", "db_bytes", "bytes")
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


def busiest(session: OrmSession, day: date, top: int) -> list[EgressLedger]:
    """The `top` rows of one day whose database connections received the most bytes."""
    return list(
        session.scalars(
            select(EgressLedger)
            .where(col(EgressLedger.day) == day)
            .order_by(col(EgressLedger.db_bytes).desc(), col(EgressLedger.route))
            .limit(top)
        ).all()
    )


@dataclass(frozen=True)
class Day:
    """One UTC day of measured egress; mb is None when the day ran statements but its
    connections measured no bytes, so the day is unknown rather than zero."""

    day: date
    mb: float | None


def day_of(day: date, statements: int, db_bytes: int) -> Day:
    return Day(day, None if statements and not db_bytes else db_bytes / 1e6)


def daily(session: OrmSession, since: date) -> list[Day]:
    """Each day from `since` on, summed over every route in SQL, oldest first."""
    found = session.execute(
        select(
            col(EgressLedger.day),
            func.sum(EgressLedger.statements),
            func.sum(EgressLedger.db_bytes),
        )
        .where(col(EgressLedger.day) >= since)
        .group_by(col(EgressLedger.day))
        .order_by(col(EgressLedger.day))
    ).all()
    return [day_of(d, int(s or 0), int(b or 0)) for d, s, b in found]
