from datetime import datetime
from sqlalchemy import ForeignKey, String, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.models.base import DBModel

class DBDraftSeries(DBModel):
    __tablename__ = 'draft_series'
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey('matches.id'))
    date_time: Mapped[datetime | None] = mapped_column()
    caster: Mapped[str | None] = mapped_column(String(50))
    player1_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    player2_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    player1_score: Mapped[int | None] = mapped_column(default=0)
    player2_score: Mapped[int | None] = mapped_column(default=0)
    host_player_id: Mapped[int] = mapped_column()
    is_fantasy_match: Mapped[bool | None] = mapped_column(default=False)
    created_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)

    match: Mapped['DBMatch'] = relationship(foreign_keys=[match_id])
    player1: Mapped['DBUser'] = relationship(foreign_keys=[player1_id])
    player2: Mapped['DBUser'] = relationship(foreign_keys=[player2_id])

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
