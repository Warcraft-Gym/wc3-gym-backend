import logging
from src.database.abstract_database_service import AbstractDatabaseService
from src.database.model.DBSeason import DBSeason
from src.database.model.DBTeam import DBTeam
from sqlalchemy.exc import SQLAlchemyError
from custom_exceptions import DBException
from src.dtos.season_dto import SeasonDTO

logger = logging.getLogger(__name__)

class SeasonDBService(AbstractDatabaseService):
    def add(self, season : SeasonDTO):
        try:
            session = self.Session()
            new_season = DBSeason.add(session, season.to_dict())
            # Example usage
            if not new_season:
                raise DBException("Season could not be created!")
            return SeasonDTO.from_dbseason(new_season)   
        except SQLAlchemyError as e:
            # Log the error and handle it
            logger.error(f"Database error: {e}")
            raise DBException(f"Database error: {e}")
        finally:
            session.close()

    def update(self, season : SeasonDTO):
        try:
            session = self.Session()
            season = DBSeason.update(session, season.id, **season.to_dict())
            # Example usage
            if not season:
                raise DBException("Season could not be updated!")
            return SeasonDTO.from_dbseason(season)   
        except SQLAlchemyError as e:
            # Log the error and handle it
            logger.error(f"Database error: {e}")
            raise DBException(f"Database error: {e}")
        finally:
            session.close()

    def delete(self, season_id):
        try:
            session = self.Session()
            DBSeason.delete(session, season_id) 
        except SQLAlchemyError as e:
            # Log the error and handle it
            logger.error(f"Database error: {e}")
            raise DBException(f"Database error: {e}")
        finally:
            session.close()

    def get(self, season_id):
        try:
            session = self.Session()
            season = session.query(DBSeason).filter_by(id=season_id).first()
            # Example usage
            if not season:
                raise DBException("Season could not be found!")
            return SeasonDTO.from_dbseason(season)   
        except SQLAlchemyError as e:
            # Log the error and handle it
            logger.error(f"Database error: {e}")
            raise DBException(f"Database error: {e}")
        finally:
            session.close()

    def addTeams(self, season_id, team_ids):
        with self.get_session() as session:
            try:
                season = session.query(DBSeason).filter_by(id=season_id).first()
                if not season:
                    raise Exception(f"Season not found by id: {season_id}")
                for team_id in team_ids:
                    team = session.query(DBTeam).filter_by(id=team_id).first()
                    if not team:
                        raise Exception(f"Team not found by id: {team_id}")
                    DBTeam.updateObject(session, team, **{'season':season})
                return SeasonDTO.from_dbseason(season)   
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def removeTeams(self, season_id, team_ids):
        with self.get_session() as session:
            try:
                season = session.query(DBSeason).filter_by(id=season_id).first()
                if not season:
                    raise Exception(f"Season not found by id: {season_id}")
                for team_id in team_ids:
                    team = session.query(DBTeam).filter_by(id=team_id).first()
                    if not team:
                        raise Exception(f"Team not found by id: {team_id}")
                    if team.season_id != season_id:
                        raise Exception(f"Team not part of season: {season.name}")
                    DBTeam.updateObject(session, team, **{'season':None})
                return SeasonDTO.from_dbseason(season)   
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")