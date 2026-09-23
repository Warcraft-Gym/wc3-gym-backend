"""What each route costs the database, one row per day, route and method.

The middleware adds one call to the row after every request it can name a
route for, so the daily egress bill splits by route without a log search.
"""

from datetime import date

from sqlalchemy import BigInteger, Text
from sqlmodel import Field, SQLModel


class EgressLedger(SQLModel, table=True):
    __tablename__ = "egress_ledger"

    day: date = Field(primary_key=True)
    # The route template, e.g. /events/{event_id}/series
    route: str = Field(sa_type=Text, primary_key=True)
    method: str = Field(sa_type=Text, primary_key=True)
    calls: int = Field(sa_type=BigInteger)
    statements: int = Field(sa_type=BigInteger)
    rows: int = Field(sa_type=BigInteger)
    bytes: int = Field(sa_type=BigInteger)
