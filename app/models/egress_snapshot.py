"""Daily copies of pg_stat_statements, so the egress of any day reads back from the database.

A daily job copies each statement's cumulative calls and rows; two copies diff into
the rows the window returned. The statement text is stored once per statement.
"""

from datetime import datetime

from sqlalchemy import BigInteger, Text
from sqlmodel import Field, SQLModel

from app.models.types import UTCDateTime


class EgressStatement(SQLModel, table=True):
    __tablename__ = "egress_statement"

    queryid: int = Field(sa_type=BigInteger, primary_key=True)
    dbid: int = Field(sa_type=BigInteger, primary_key=True)
    # The first 150 characters, whitespace collapsed
    query: str = Field(sa_type=Text)


class EgressSnapshot(SQLModel, table=True):
    __tablename__ = "egress_snapshot"

    taken_at: datetime = Field(sa_type=UTCDateTime, primary_key=True)
    queryid: int = Field(sa_type=BigInteger, primary_key=True)
    dbid: int = Field(sa_type=BigInteger, primary_key=True)
    # The oid of the role that ran the statement
    userid: int = Field(sa_type=BigInteger, primary_key=True)
    # False for a statement nested inside a function
    toplevel: bool = Field(primary_key=True)
    # Cumulative since the statistics were last reset
    calls: int = Field(sa_type=BigInteger)
    rows: int = Field(sa_type=BigInteger)


class EgressStatementRows(SQLModel):
    """One statement's share of a window."""

    query: str
    calls: int
    rows: int


class EgressWindow(SQLModel):
    """The rows returned between two snapshots and the egress they bill."""

    start: datetime
    end: datetime
    hours: float
    calls: int
    rows: int
    estimated_mb: float
    mb_per_day: float
    over_budget: bool


class EgressSnapshotResult(SQLModel):
    """What one run recorded; `window` is None on the first run and on a skipped run."""

    available: bool
    reason: str | None = None
    # Set when the run wrote nothing because the last snapshot is under an hour old
    skipped: str | None = None
    taken_at: datetime | None = None
    statements: int = 0
    budget_mb_per_day: float
    window: EgressWindow | None = None
    top: list[EgressStatementRows] = Field(default_factory=list)
