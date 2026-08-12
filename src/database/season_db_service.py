import logging
from src.database.abstract_database_service import AbstractDatabaseService
from src.database.model.DBSeason import DBSeason
from sqlalchemy.orm import joinedload, noload
from custom_exceptions import DBException
from src.schemas.season import Season
from src.util.query_util import QueryUtil

logger = logging.getLogger(__name__)

class SeasonDBService(AbstractDatabaseService):
    def add(self, season : Season):
        with self.get_session() as session:
            new_season = DBSeason.add(session, season.to_db_dict())
            # Example usage
            if not new_season:
                raise DBException("Season could not be created!")
            return Season.from_dbseason(new_season)   

    def update(self, season : Season):
        with self.get_session() as session:
            season = DBSeason.update(session, season.id, **season.to_db_dict())
            # Example usage
            if not season:
                raise DBException("Season could not be updated!")
            return Season.from_dbseason(season)   

    def delete(self, season_id):
        with self.get_session() as session:
            DBSeason.delete(session, season_id) 

    def get(self, season_id):
        with self.get_session() as session:
            from src.database.model.DBRelationships import DBMapSeason
            from src.database.model.DBMap import DBMap
            # Eager load related entities, disable nested loading except for maps
            season = session.query(DBSeason)\
                .options(
                    joinedload(DBSeason.user_teams).noload('*'),
                    joinedload(DBSeason.teams).noload('*'),
                    joinedload(DBSeason.maps).joinedload(DBMapSeason.map),
                    noload(DBSeason.signup_users)
                )\
                .filter_by(id=season_id).first()
            # Example usage
            if not season:
                raise DBException("Season could not be found!")
            return Season.from_dbseason(season)   


    def getAll(self):
        with self.get_session() as session:
            result = []
            from src.database.model.DBRelationships import DBMapSeason
            from src.database.model.DBMap import DBMap
            # Eager load related entities, disable nested loading except for maps
            seasons = session.query(DBSeason)\
                .options(
                    joinedload(DBSeason.user_teams).noload('*'),
                    joinedload(DBSeason.teams).noload('*'),
                    joinedload(DBSeason.maps).joinedload(DBMapSeason.map),
                    noload(DBSeason.signup_users)
                ).all()
            for season in seasons:
                result.append(Season.from_dbseason(season))
            return result

    def addTeams(self, season_id, team_ids):
        with self.get_session() as session:
            season =  DBSeason.addTeams(session, season_id, team_ids)
            if not season:
                raise DBException("Season could not be updated!")
            return Season.from_dbseason(season)   

    def search(self, query):
        with self.get_session() as session:
            result = []
            from src.database.model.DBRelationships import DBMapSeason
            from src.database.model.DBMap import DBMap
            filter = QueryUtil.convertQueryToDBFilter(DBSeason, query)
            # Eager load related entities, disable nested loading except for maps
            seasons = session.query(DBSeason)\
                .options(
                    joinedload(DBSeason.user_teams).noload('*'),
                    joinedload(DBSeason.teams).noload('*'),
                    joinedload(DBSeason.maps).joinedload(DBMapSeason.map),
                    noload(DBSeason.signup_users)
                )\
                .filter(filter).all() if filter is not None else []
            if not seasons:
                logger.debug(f"No seasons found by searchcriteria: {query}")
                return result
            for season in seasons:
                result.append(Season.from_dbseason(season))
            return result

    def removeTeams(self, season_id, team_ids):
        with self.get_session() as session:
            season =  DBSeason.removeTeams(session, season_id, team_ids)
            if not season:
                raise DBException("Season could not be updated!")
            return Season.from_dbseason(season)   
            
    def addMaps(self, season_id, map_ids):
        with self.get_session() as session:
            season = DBSeason.addMaps(session, season_id, map_ids)
            return Season.from_dbseason(season)   

    def removeMaps(self, season_id, map_ids):
        with self.get_session() as session:
            season = DBSeason.removeMaps(session, season_id, map_ids)
            return Season.from_dbseason(season)   

    def addUserSignup(self, season_id, user_ids):
        with self.get_session() as session:
            season = DBSeason.addUserSignup(session, season_id, user_ids)
            if not season:
                raise DBException("Season could not be updated!")
            return Season.from_dbseason(season)

    def removeUserSignup(self, season_id, user_ids):
        with self.get_session() as session:
            season = DBSeason.removeUserSignup(session, season_id, user_ids)
            if not season:
                raise DBException("Season could not be updated!")
            return Season.from_dbseason(season)

    def getSignedUpUsers(self, season_id):
        with self.get_session() as session:
            from src.database.model.DBRelationships import DBUserSeasonSignup
            from src.database.model.DBUser import DBUser
            from src.schemas.user import User
                
            # Eager load signup users with their user data and w3c_stats
            season = session.query(DBSeason)\
                .options(
                    joinedload(DBSeason.signup_users).joinedload(DBUserSeasonSignup.user).joinedload(DBUser.w3c_stats).noload('*'),
                    joinedload(DBSeason.signup_users).joinedload(DBUserSeasonSignup.user).joinedload(DBUser.team_seasons).noload('*')
                )\
                .filter_by(id=season_id).first()
                
            if not season:
                raise DBException("Season could not be found!")
                
            result = []
            if season.signup_users:
                for signup in season.signup_users:
                    if signup.user:
                        user_dto = User.from_dbuser(signup.user)
                        if user_dto:
                            result.append(user_dto)
                
            return result
