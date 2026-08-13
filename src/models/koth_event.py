from datetime import datetime
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.models.base import DBModel

class DBKothEvent(DBModel):
    __tablename__ = 'koth_events'
    __table_args__ = {'mysql_charset': 'utf8mb4'}

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(500))
    event_date: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    is_active: Mapped[bool] = mapped_column(default=True)
    bracket_1_threshold: Mapped[int] = mapped_column(default=1450)  # < this value
    bracket_2_threshold: Mapped[int] = mapped_column(default=1600)  # >= bracket_1 and < this value
    # bracket 3 is >= bracket_2_threshold

    # Relationships
    signups: Mapped[list['DBKothSignup']] = relationship(back_populates='event', cascade='all, delete-orphan')
    matches: Mapped[list['DBKothMatch']] = relationship(back_populates='event', cascade='all, delete-orphan')
