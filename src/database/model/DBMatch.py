from sqlalchemy import Column, Integer, String, Sequence, ForeignKey
from sqlalchemy.orm import relationship
from src.database.model.DBModel import DBModel



class DBMatch(DBModel):
    __tablename__ = 'matches'
    id = Column(Integer, Sequence(f'{__name__.lower()}_id_seq'), primary_key=True)
    team1_id = Column(Integer, ForeignKey('teams.id', ondelete='CASCADE'))
    team2_id = Column(Integer, ForeignKey('teams.id', ondelete='CASCADE'))
    season_id = Column(Integer, ForeignKey('seasons.id', ondelete='CASCADE'))
    playday = Column(Integer)
    team1_score = Column(Integer)
    team2_score = Column(Integer)
    fixed_map_id = Column(Integer, ForeignKey('maps.id'))

    team1 = relationship("DBTeam", foreign_keys=[team1_id])
    team2 = relationship("DBTeam", foreign_keys=[team2_id])
    season = relationship("DBSeason", foreign_keys=[season_id])
    fixed_map = relationship("DBMap", foreign_keys=[fixed_map_id])

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}