from src.database.abstract_database_service import AbstractDatabaseService
from src.models.player_career_stats import DBPlayerCareerStats
from src.models.user import DBUser
from src.schemas.player_career_stats import PlayerCareerStats
from custom_exceptions import DBException
from sqlalchemy import select
import logging

logger = logging.getLogger(__name__)

class PlayerCareerStatsDBService(AbstractDatabaseService):
    def get(self, stat_id: int):
        """Get career stats by stats record ID (implements abstract method)"""
        with self.get_session() as session:
            stat = session.get(DBPlayerCareerStats, stat_id)
            return PlayerCareerStats.from_db(stat) if stat else None
    
    def add(self, entity):
        """Add new career stats record (implements abstract method)"""
        with self.get_session() as session:
            new_stat = DBPlayerCareerStats.add(session, entity)
            return PlayerCareerStats.from_db(new_stat)
    
    def update(self, stat_dto):
        """Update career stats record (implements abstract method)"""
        with self.get_session() as session:
            updated_stat = DBPlayerCareerStats.update(session, stat_dto.id, **stat_dto.to_db_dict())
            return PlayerCareerStats.from_db(updated_stat)
    
    def delete(self, stat_id: int):
        """Delete career stats by stats ID (implements abstract method)"""
        with self.get_session() as session:
            stats = session.get(DBPlayerCareerStats, stat_id)
            if stats:
                session.delete(stats)
                return True
            return False

    def get_all(self):
        """Get all player career stats ordered by rating"""
        with self.get_session() as session:
            stats = session.scalars(
                select(DBPlayerCareerStats)
                .order_by(DBPlayerCareerStats.rating.desc())
            ).unique().all()
            return [PlayerCareerStats.from_db(stat) for stat in stats]

    def get_by_user_id(self, user_id: int):
        """Get career stats for a specific user"""
        with self.get_session() as session:
            stat = session.scalars(
                select(DBPlayerCareerStats)
                .where(DBPlayerCareerStats.user_id == user_id)
                .limit(1)
            ).first()
            return PlayerCareerStats.from_db(stat) if stat else None

    def get_by_player_name(self, player_name: str):
        """Get career stats by player name (for unmapped historical records)"""
        with self.get_session() as session:
            stat = session.scalars(
                select(DBPlayerCareerStats)
                .where(DBPlayerCareerStats.player_name == player_name)
                .limit(1)
            ).first()
            return PlayerCareerStats.from_db(stat) if stat else None

    def get_or_create(self, user_id: int):
        """Get existing stats or create new record for user"""
        with self.get_session() as session:
            stats = session.scalars(
                select(DBPlayerCareerStats)
                .where(DBPlayerCareerStats.user_id == user_id)
                .limit(1)
            ).first()

            if not stats:
                # Get user name for player_name
                user = session.get(DBUser, user_id)
                player_name = user.name if user else f"User_{user_id}"

                stats = DBPlayerCareerStats(user_id=user_id, player_name=player_name)
                session.add(stats)
                session.flush()

            return PlayerCareerStats.from_db(stats)

    def update_historical_baseline(self, player_name: str, rating: int,
                                   series_won: int, series_lost: int, games_won: int,
                                   games_lost: int, seasons_played: int, series_winrate: float,
                                   games_winrate: float, avg_series: float):
        """Update historical baseline columns (from CSV import).

        Resolves the user by player name in the same transaction, so one
        CSV row is one short transaction.
        """
        with self.get_session() as session:
            user = session.scalars(
                select(DBUser).where(DBUser.name == player_name).limit(1)
            ).first()
            user_id = user.id if user else None
            if not user:
                logger.info(f"User not found for {player_name}, importing anyway with null user_id")

            # Find by player_name first
            stats = session.scalars(
                select(DBPlayerCareerStats)
                .where(DBPlayerCareerStats.player_name == player_name)
                .limit(1)
            ).first()
            
            if stats:
                # Update existing - also update user_id if provided and currently null
                if user_id and not stats.user_id:
                    stats.user_id = user_id
                stats.historical_rating = rating
                stats.historical_series_won = series_won
                stats.historical_series_lost = series_lost
                stats.historical_games_won = games_won
                stats.historical_games_lost = games_lost
                stats.historical_seasons_played = seasons_played
            else:
                # Create new with historical baseline
                stats = DBPlayerCareerStats(
                    user_id=user_id,
                    player_name=player_name,
                    historical_rating=rating,
                    historical_series_won=series_won,
                    historical_series_lost=series_lost,
                    historical_games_won=games_won,
                    historical_games_lost=games_lost,
                    historical_seasons_played=seasons_played,
                    # Set totals to historical initially
                    rating=rating,
                    series_won=series_won,
                    series_lost=series_lost,
                    series_winrate=series_winrate,
                    games_won=games_won,
                    games_lost=games_lost,
                    games_winrate=games_winrate,
                    seasons_played=seasons_played,
                    avg_series_per_season=avg_series
                )
                session.add(stats)

    def update_totals(self, user_id: int, rating: int, series_won: int, series_lost: int,
                     series_winrate: float, games_won: int, games_lost: int, 
                     games_winrate: float, seasons_played: int, avg_series: float):
        """Update combined total columns (from recalculation)"""
        with self.get_session() as session:
            stats = session.scalars(
                select(DBPlayerCareerStats)
                .where(DBPlayerCareerStats.user_id == user_id)
                .limit(1)
            ).first()

            if stats:
                stats.rating = rating
                stats.series_won = series_won
                stats.series_lost = series_lost
                stats.series_winrate = round(series_winrate, 2)
                stats.games_won = games_won
                stats.games_lost = games_lost
                stats.games_winrate = round(games_winrate, 2)
                stats.seasons_played = seasons_played
                stats.avg_series_per_season = round(avg_series, 2)
    
    def batch_update_stats(self, updates):
        """Batch update stats for multiple users.

        Each item runs in its own transaction. An error in one item does
        not affect the other items, and a transaction error such as a
        deadlock can only lose the one item that hit it.

        Args:
            updates: List of dicts with 'user_id', 'player_name', and stat values

        Returns:
            Dict with 'updated' count and 'errors' list
        """
        updated = 0
        errors = []

        for update_data in updates:
            user_id = update_data.get('user_id')
            try:
                with self.get_session() as session:
                    self._apply_stats_update(session, update_data)
                updated += 1
            except (DBException, KeyError) as e:
                # DBException: database error for this item.
                # KeyError: the item misses a required field.
                # Any other exception is a bug and must fail the request.
                logger.error(f"Error updating stats for user {user_id}: {e}")
                errors.append(f"Error for user {user_id}: {str(e)}")

        return {'updated': updated, 'errors': errors}

    def _apply_stats_update(self, session, update_data):
        """Create, link, or merge the stats record for one update item."""
        user_id = update_data['user_id']
        player_name = update_data['player_name']

        # Query for both potential records separately to handle merging
        # Only query by user_id if it's not None (unmapped records have user_id=None)
        record_by_user_id = None
        if user_id is not None:
            record_by_user_id = session.scalars(
                select(DBPlayerCareerStats)
                .where(DBPlayerCareerStats.user_id == user_id)
                .limit(1)
            ).first()
        record_by_name = session.scalars(
            select(DBPlayerCareerStats)
            .where(DBPlayerCareerStats.player_name == player_name)
            .limit(1)
        ).first()

        # Handle different scenarios
        if record_by_user_id and record_by_name and record_by_user_id.id != record_by_name.id:
            # Two separate records exist - merge historical into user_id record
            logger.info(f"Merging records for {player_name}: user_id record {record_by_user_id.id} and name record {record_by_name.id}")
            stats_record = record_by_user_id
            # Keep existing player_name, don't overwrite with current name

            # Preserve historical data from the name-based record if it has any
            if record_by_name.historical_rating:
                stats_record.historical_rating = record_by_name.historical_rating
                stats_record.historical_series_won = record_by_name.historical_series_won
                stats_record.historical_series_lost = record_by_name.historical_series_lost
                stats_record.historical_games_won = record_by_name.historical_games_won
                stats_record.historical_games_lost = record_by_name.historical_games_lost
                stats_record.historical_seasons_played = record_by_name.historical_seasons_played

            # Delete the duplicate record
            session.delete(record_by_name)

        elif record_by_user_id:
            # Only user_id record exists - update stats only
            # Don't change player_name (historical data should not change)
            stats_record = record_by_user_id

        elif record_by_name:
            # Only name-based record exists (historical) - link it to user_id
            # Don't change player_name (preserve historical name)
            stats_record = record_by_name
            stats_record.user_id = user_id

        else:
            # No existing record - create new with provided name
            stats_record = DBPlayerCareerStats(
                user_id=user_id,
                player_name=player_name
            )
            session.add(stats_record)

        # Update all stat fields
        stats_record.rating = update_data['rating']
        stats_record.series_won = update_data['series_won']
        stats_record.series_lost = update_data['series_lost']
        stats_record.series_winrate = update_data['series_winrate']
        stats_record.games_won = update_data['games_won']
        stats_record.games_lost = update_data['games_lost']
        stats_record.games_winrate = update_data['games_winrate']
        stats_record.seasons_played = update_data['seasons_played']
        stats_record.avg_series_per_season = update_data['avg_series_per_season']
