from sqlalchemy import Column, Integer, String, Sequence, Date
from sqlalchemy.orm import relationship
from sqlalchemy.orm.session import Session
from src.database.model.DBModel import DBModel
from src.database.model.DBRelationships import DBTeamSeason
from src.database.model.DBRelationships import DBMapSeason
from src.database.model.DBTeam import DBTeam
from src.database.model.DBMap import DBMap
from src.database.model.DBRelationships import DBUserSeasonSignup
from src.database.model.DBUser import DBUser


class DBSeason(DBModel):
    __tablename__ = 'seasons'
    id = Column(Integer, Sequence(f'{__name__.lower()}_id_seq'), primary_key=True)
    name = Column(String(50), nullable=False)
    number_weeks =  Column(Integer, nullable=False)
    series_per_week = Column(Integer, nullable=False)
    pick_ban = Column(String(100))
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    user_teams = relationship('DBUserTeamSeason', back_populates='season', cascade="all, delete")
    teams = relationship('DBTeamSeason', back_populates='season', cascade="all, delete")
    maps = relationship('DBMapSeason', back_populates='season', cascade="all, delete")
    signup_users = relationship('DBUserSeasonSignup', back_populates='season', cascade="all, delete")
    discordRole = Column(String(50))

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
    

    @classmethod
    def addTeams(cls, session: Session, obj_id, team_ids):
        season = session.query(cls).filter_by(id=obj_id).first()
        if not season:
            raise Exception(f"Season not found by id: {obj_id}")
        for team_id in team_ids:
            team = session.query(DBTeam).filter_by(id=team_id).first()
            if not team:
                raise Exception(f"Team not found by id: {team_id}")
            already_exists = session.query(DBTeamSeason).filter_by(season_id=obj_id,team_id=team.id).first() is not None
            if not already_exists:
                session.add(DBTeamSeason(season=season,team=team))

        session.flush()
        return season
    
    @classmethod
    def removeTeams(cls, session: Session, obj_id, team_ids):
        season = session.query(cls).filter_by(id=obj_id).first()
        if not season:
            raise Exception(f"Season not found by id: {obj_id}")
        for team_id in team_ids:
            team = session.query(DBTeam).filter_by(id=team_id).first()
            if not team:
                raise Exception(f"Team not found by id: {team_id}")
            team_season = session.query(DBTeamSeason).filter_by(season_id=obj_id,team_id=team_id).first()
            if not team_season:
                raise Exception(f"Team not part of the season, team id: {team_id}, season id {obj_id}")
            session.delete(team_season)
        session.flush()
        return season
    

    @classmethod
    def addMaps(cls, session: Session, obj_id, map_ids):
        season = session.query(cls).filter_by(id=obj_id).first()
        if not season:
            raise Exception(f"Season not found by id: {obj_id}")
        for map_id in map_ids:
            map = session.query(DBMap).filter_by(id=map_id).first()
            if not map:
                raise Exception(f"Map not found by id: {map_id}")
            already_exists = session.query(DBMapSeason).filter_by(season_id=obj_id,map_id=map.id).first() is not None
            if not already_exists:
                session.add(DBMapSeason(season=season,map=map)) 

        session.flush()
        return season
    
    @classmethod
    def removeMaps(cls, session: Session, obj_id, map_ids):
        season = session.query(cls).filter_by(id=obj_id).first()
        if not season:
            raise Exception(f"Season not found by id: {obj_id}")
        for map_id in map_ids:
            map = session.query(DBMap).filter_by(id=map_id).first()
            if not map:
                raise Exception(f"Map not found by id: {map_id}")
            map_season = session.query(DBMapSeason).filter_by(season_id=obj_id,map_id=map.id).first()
            if not map_season:
                raise Exception(f"Map not part of the season, map id: {map_id}, season id {obj_id}")
            session.delete(map_season)

        session.flush()
        return season
    
    @classmethod
    def addUserSignup(cls, session: Session, obj_id, user_ids):
        season = session.query(cls).filter_by(id=obj_id).first()
        if not season:
            raise Exception(f"Season not found by id: {obj_id}")
        for user_id in user_ids:
            user = session.query(DBUser).filter_by(id=user_id).first()
            if not user:
                raise Exception(f"User not found by id: {user_id}")
            already_exists = session.query(DBUserSeasonSignup).filter_by(season_id=obj_id,user_id=user.id).first() is not None
            if not already_exists:
                session.add(DBUserSeasonSignup(season=season,user=user)) 

        session.flush()
        return season
    
    @classmethod
    def removeUserSignup(cls, session: Session, obj_id, user_ids):
        season = session.query(cls).filter_by(id=obj_id).first()
        if not season:
            raise Exception(f"Season not found by id: {obj_id}")
        for user_id in user_ids:
            user = session.query(DBUser).filter_by(id=user_id).first()
            if not user:
                raise Exception(f"User not found by id: {user_id}")
            user_season = session.query(DBUserSeasonSignup).filter_by(season_id=obj_id,user_id=user.id).first()
            if not user_season:
                raise Exception(f"User not signed up for the season, user id: {user_id}, season id {obj_id}")
            session.delete(user_season)

        session.flush()
        return season