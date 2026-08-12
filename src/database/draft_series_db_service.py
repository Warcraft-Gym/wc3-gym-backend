import logging
from src.database.abstract_database_service import AbstractDatabaseService
from src.database.model.DBDraftSeries import DBDraftSeries
from src.database.model.DBUser import DBUser
from src.database.model.DBRelationships import DBUserTeamSeason
from src.database.model.DBMatch import DBMatch
from sqlalchemy.orm import joinedload
from custom_exceptions import DBException
from src.schemas.draft_series import DraftSeries

logger = logging.getLogger(__name__)

class DraftSeriesDBService(AbstractDatabaseService):
    def add(self, draft_series: DraftSeries):
        with self.get_session() as session:
            draft_series = DBDraftSeries.add(session, draft_series.to_db_dict())
            if not draft_series:
                raise DBException("Draft series could not be created!")
            return DraftSeries.from_db_draft_series(draft_series)

    def update(self, draft_series: DraftSeries):
        with self.get_session() as session:
            draft_series = DBDraftSeries.update(session, draft_series.id, **draft_series.to_db_dict())
            if not draft_series:
                raise DBException("Draft series could not be updated!")
            return DraftSeries.from_db_draft_series(draft_series)

    def delete(self, draft_series_id):
        with self.get_session() as session:
            DBDraftSeries.delete(session, draft_series_id)

    def get(self, draft_series_id):
        with self.get_session() as session:
            # Eager load relationships to avoid N+1 queries
            draft_series = session.query(DBDraftSeries)\
                .options(
                    joinedload(DBDraftSeries.match).joinedload(DBMatch.team1),
                    joinedload(DBDraftSeries.match).joinedload(DBMatch.team2),
                    joinedload(DBDraftSeries.player1).joinedload(DBUser.w3c_stats),
                    joinedload(DBDraftSeries.player1).joinedload(DBUser.team_seasons).joinedload(DBUserTeamSeason.season),
                    joinedload(DBDraftSeries.player2).joinedload(DBUser.w3c_stats),
                    joinedload(DBDraftSeries.player2).joinedload(DBUser.team_seasons).joinedload(DBUserTeamSeason.season)
                )\
                .filter_by(id=draft_series_id).first()
            if not draft_series:
                raise DBException("Draft series could not be found")
            return DraftSeries.from_db_draft_series(draft_series)

    def getByMatchId(self, match_id):
        with self.get_session() as session:
            result = []
            # Eager load relationships
            draft_series_list = session.query(DBDraftSeries)\
                .options(
                    joinedload(DBDraftSeries.match).joinedload(DBMatch.team1),
                    joinedload(DBDraftSeries.match).joinedload(DBMatch.team2),
                    joinedload(DBDraftSeries.player1).joinedload(DBUser.w3c_stats),
                    joinedload(DBDraftSeries.player1).joinedload(DBUser.team_seasons).joinedload(DBUserTeamSeason.season),
                    joinedload(DBDraftSeries.player2).joinedload(DBUser.w3c_stats),
                    joinedload(DBDraftSeries.player2).joinedload(DBUser.team_seasons).joinedload(DBUserTeamSeason.season)
                )\
                .filter_by(match_id=match_id).all()
            for single_draft_series in draft_series_list:
                result.append(DraftSeries.from_db_draft_series(single_draft_series))
            return result

    def deleteByMatchId(self, match_id):
        """Delete all draft series for a given match"""
        with self.get_session() as session:
            session.query(DBDraftSeries).filter_by(match_id=match_id).delete()
