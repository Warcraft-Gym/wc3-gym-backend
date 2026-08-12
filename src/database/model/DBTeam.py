from sqlalchemy import Column, Integer, String, Sequence, ForeignKey, LargeBinary
from sqlalchemy.orm import relationship
from sqlalchemy.orm.session import Session
from src.database.model.DBModel import DBModel
from src.database.model.DBUser import DBUser
from src.database.model.DBRelationships import DBUserTeamSeason


class DBTeam(DBModel):
    __tablename__ = 'teams'
    id = Column(Integer, Sequence(f'{__name__.lower()}_id_seq'), primary_key=True)
    name = Column(String(50), nullable=False)
    long_name = Column(String(100))
    icon = Column(LargeBinary)
    discord_role = Column(String(50))
    user_seasons = relationship('DBUserTeamSeason', back_populates='team', cascade="all, delete")
    season_info = relationship('DBTeamSeason', back_populates='team', cascade="all, delete")

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
    
    @classmethod
    def addPlayers(cls, session: Session, obj_id, season_id, user_ids):
        from src.database.model.DBSeason import DBSeason
        team = session.query(cls).filter_by(id=obj_id).first()
        if not team:
            raise Exception(f"Team not found by id: {obj_id}")
        season = session.query(DBSeason).filter_by(id=season_id).first()
        if not season:
            raise Exception(f"Season not found by id: {season_id}")
        for user_id in user_ids:
            user = session.query(DBUser).filter_by(id=user_id).first()
            if not user:
                raise Exception(f"User not found by id: {user_id}")
            already_exists = session.query(DBUserTeamSeason).filter_by(team_id=team.id,season_id=season_id,user_id=user.id).first() is not None
            if not already_exists:
                session.add(DBUserTeamSeason(user=user,season=season,team=team)) 
                         
        session.flush()
        return team

    @classmethod
    def removePlayers(cls, session: Session, obj_id, season_id, user_ids):
        from src.database.model.DBSeason import DBSeason
        team = session.query(cls).filter_by(id=obj_id).first()
        if not team:
            raise Exception(f"Team not found by id: {obj_id}")
        season = session.query(DBSeason).filter_by(id=season_id).first()
        if not season:
            raise Exception(f"Season not found by id: {season_id}")
        for user_id in user_ids:
            user = session.query(DBUser).filter_by(id=user_id).first()
            if not user:
                raise Exception(f"User not found by id: {user_id}")
            user_team = session.query(DBUserTeamSeason).filter_by(team_id=obj_id,season_id=season_id,user_id=user.id).first()
            if not user_team:
                raise Exception(f"User not part of the team, user id: {user_id}")
            session.delete(user_team)                
        session.flush()
        return team
    
    @classmethod
    def update_icon(cls, session: Session, obj_id, file):
        obj = session.query(cls).filter_by(id=obj_id).first()
        if obj:
            setattr(obj, DBTeam.icon.name, file)
            session.flush()
        return obj
    
    @classmethod
    def setCoaches(cls, session: Session, team_id, season_id, user_ids):
        """Set coaches for a team in a season (up to 3)."""
        from src.database.model.DBSeason import DBSeason
        from src.database.model.DBRelationships import DBTeamSeason
        
        team = session.query(cls).filter_by(id=team_id).first()
        if not team:
            raise Exception(f"Team not found by id: {team_id}")
        season = session.query(DBSeason).filter_by(id=season_id).first()
        if not season:
            raise Exception(f"Season not found by id: {season_id}")
        
        # Validate coach limit
        if len(user_ids) > 3:
            raise Exception("Cannot assign more than 3 coaches per team per season")
        
        # Validate all users exist
        for user_id in user_ids:
            user = session.query(DBUser).filter_by(id=user_id).first()
            if not user:
                raise Exception(f"User not found by id: {user_id}")
        
        # Get or create team_season entry
        team_season = session.query(DBTeamSeason).filter_by(
            team_id=team_id,
            season_id=season_id
        ).first()
        
        if not team_season:
            team_season = DBTeamSeason(team_id=team_id, season_id=season_id)
            session.add(team_season)
        
        # Set coaches (pad with None if less than 3)
        team_season.coach_1_id = user_ids[0] if len(user_ids) > 0 else None
        team_season.coach_2_id = user_ids[1] if len(user_ids) > 1 else None
        team_season.coach_3_id = user_ids[2] if len(user_ids) > 2 else None
        
        session.flush()
        return team