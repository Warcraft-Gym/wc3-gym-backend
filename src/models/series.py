from datetime import datetime
from sqlalchemy import ForeignKey, String, and_, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship
from src.models.base import DBModel
from src.models.match import DBMatch

class DBSeries(DBModel):
    __tablename__ = 'series'
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey('matches.id', ondelete='CASCADE'))
    date_time: Mapped[datetime | None] = mapped_column()
    caster: Mapped[str | None] = mapped_column(String(50))
    player1_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'))
    player2_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'))
    player1_score: Mapped[int | None] = mapped_column()
    player2_score: Mapped[int | None] = mapped_column()
    player1_points: Mapped[int | None] = mapped_column()
    player2_points: Mapped[int | None] = mapped_column()
    host_player_id: Mapped[int] = mapped_column()
    is_fantasy_match: Mapped[bool | None] = mapped_column()

    match: Mapped['DBMatch'] = relationship(foreign_keys=[match_id])
    player1: Mapped['DBUser'] = relationship(foreign_keys=[player1_id])
    player2: Mapped['DBUser'] = relationship(foreign_keys=[player2_id])

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

    @classmethod
    def searchForSeasonAndPlayday(cls, session: Session, season_id, playday, filters):
        from sqlalchemy.orm import joinedload
        from src.models.user import DBUser
        from src.models.relationships import DBUserTeamSeason

        stmt = select(cls).options(
            joinedload(cls.match).joinedload(DBMatch.team1),
            joinedload(cls.match).joinedload(DBMatch.team2),
            joinedload(cls.player1).joinedload(DBUser.w3c_stats),
            joinedload(cls.player1).joinedload(DBUser.team_seasons).joinedload(DBUserTeamSeason.season),
            joinedload(cls.player2).joinedload(DBUser.w3c_stats),
            joinedload(cls.player2).joinedload(DBUser.team_seasons).joinedload(DBUserTeamSeason.season)
        )

        stmt = stmt.where(cls.match.has(and_(DBMatch.season_id == season_id, DBMatch.playday == playday)))
        if filters is not None:
            stmt = stmt.where(filters)
        return session.scalars(stmt).unique().all()

    @classmethod
    def searchForSeason(cls, session: Session, season_id, filters):
        from sqlalchemy.orm import joinedload
        from src.models.user import DBUser
        from src.models.relationships import DBUserTeamSeason

        stmt = select(cls).options(
            joinedload(cls.match).joinedload(DBMatch.team1),
            joinedload(cls.match).joinedload(DBMatch.team2),
            joinedload(cls.player1).joinedload(DBUser.w3c_stats),
            joinedload(cls.player1).joinedload(DBUser.team_seasons).joinedload(DBUserTeamSeason.season),
            joinedload(cls.player2).joinedload(DBUser.w3c_stats),
            joinedload(cls.player2).joinedload(DBUser.team_seasons).joinedload(DBUserTeamSeason.season)
        )

        stmt = stmt.where(cls.match.has(DBMatch.season_id == season_id))
        if filters is not None:
            stmt = stmt.where(filters)
        return session.scalars(stmt).unique().all()
