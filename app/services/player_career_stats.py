import logging
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session as OrmSession

from app.core.career import (
    GNL_RATING_DECAY_RATE_PER_SEASON,
    GNL_RATING_FLAT_MULTIPLIER,
    GNL_RATING_MATCH_LOSS_VALUE,
    GNL_RATING_MATCH_WIN_VALUE,
    GNL_RATING_SEASON_PLAYED_VALUE,
)
from app.models.player_career_stats import (
    PlayerCareerStats,
    PlayerCareerStatsPublic,
)
from app.models.user import User
from app.services import derived
from app.services.base import BaseService
from app.services.series import CareerSeriesRow, SeriesService

logger = logging.getLogger(__name__)


class PlayerCareerStatsService(BaseService):
    def __init__(self, series_service: SeriesService) -> None:
        self.series_service = series_service

    def get(self, stat_id: int) -> PlayerCareerStatsPublic | None:
        """Get career stats by stats record ID (implements abstract method)"""
        with self.get_session() as session:
            stat = session.get(
                PlayerCareerStats, stat_id, options=PlayerCareerStats.eager_options()
            )
            if not stat:
                return None
            public = PlayerCareerStatsPublic.from_career_stats(stat)
            derived.fill_career(session, [public])
            return public

    def add(self, entity: dict[str, Any]) -> PlayerCareerStatsPublic | None:
        """Add new career stats record (implements abstract method)"""
        with self.get_session() as session:
            new_stat = PlayerCareerStats.add(session, entity)
            return PlayerCareerStatsPublic.from_career_stats(new_stat)

    def update(self, stats: PlayerCareerStatsPublic) -> PlayerCareerStatsPublic | None:
        """Update career stats record (implements abstract method)"""
        with self.get_session() as session:
            updated_stat = PlayerCareerStats.update(
                session, stats.id, **stats.model_dump(exclude_unset=True)
            )
            return PlayerCareerStatsPublic.from_career_stats(updated_stat)

    def delete(self, stat_id: int) -> bool:
        """Delete career stats by stats ID (implements abstract method)"""
        with self.get_session() as session:
            stats = session.get(PlayerCareerStats, stat_id)
            if stats:
                session.delete(stats)
                return True
            return False

    def _stored_rows(self, session: OrmSession) -> list[PlayerCareerStatsPublic]:
        """Every stored career row, by id, with the player it carries."""
        stats = (
            session.scalars(
                select(PlayerCareerStats)
                .options(*PlayerCareerStats.eager_options())
                .order_by(PlayerCareerStats.id)
            )
            .unique()
            .all()
        )
        return [PlayerCareerStatsPublic.from_career_stats(stat) for stat in stats]

    def get_all(
        self, limit: int | None = None, offset: int = 0
    ) -> tuple[list[PlayerCareerStatsPublic], int]:
        """The career stats by rating, or one page of them, and the total count

        The rating orders the rows and the id breaks a tie, so offset paging
        walks a fixed order.
        """
        with self.get_session() as session:
            rows = derived.career_rows(session, self._stored_rows(session))
            end = None if limit is None else offset + limit
            return rows[offset:end], len(rows)

    def get_by_user_id(self, user_id: int) -> PlayerCareerStatsPublic | None:
        """Get career stats for a specific user"""
        with self.get_session() as session:
            stat = session.scalars(
                select(PlayerCareerStats)
                .options(*PlayerCareerStats.eager_options())
                .where(PlayerCareerStats.user_id == user_id)
                .limit(1)
            ).first()
            if not stat:
                return None
            public = PlayerCareerStatsPublic.from_career_stats(stat)
            derived.fill_career(session, [public])
            return public

    def get_by_player_name(self, player_name: str) -> PlayerCareerStatsPublic | None:
        """Get career stats by player name (for unmapped historical records)"""
        with self.get_session() as session:
            stat = session.scalars(
                select(PlayerCareerStats)
                .options(*PlayerCareerStats.eager_options())
                .where(PlayerCareerStats.player_name == player_name)
                .limit(1)
            ).first()
            if not stat:
                return None
            public = PlayerCareerStatsPublic.from_career_stats(stat)
            derived.fill_career(session, [public])
            return public

    def get_or_create(self, user_id: int) -> PlayerCareerStatsPublic | None:
        """Get existing stats or create new record for user"""
        with self.get_session() as session:
            stats = session.scalars(
                select(PlayerCareerStats)
                .where(PlayerCareerStats.user_id == user_id)
                .limit(1)
            ).first()

            if not stats:
                # Get user name for player_name
                user = session.get(User, user_id)
                player_name = user.name if user else f"User_{user_id}"

                stats = PlayerCareerStats(user_id=user_id, player_name=player_name)
                session.add(stats)
                session.flush()

            return PlayerCareerStatsPublic.from_career_stats(stats)

    def update_historical_baseline(
        self,
        player_name: str,
        rating: int,
        series_won: int,
        series_lost: int,
        games_won: int,
        games_lost: int,
        seasons_played: int,
        series_winrate: float,
        games_winrate: float,
        avg_series: float,
    ) -> None:
        """Update historical baseline columns (from CSV import).

        Resolves the user by player name in the same transaction, so one
        CSV row is one short transaction.
        """
        with self.get_session() as session:
            user = session.scalars(
                select(User).where(User.name == player_name).limit(1)
            ).first()
            user_id = user.id if user else None
            if not user:
                logger.info(
                    f"User not found for {player_name}, importing anyway with null user_id"
                )

            # Find by player_name first
            stats = session.scalars(
                select(PlayerCareerStats)
                .where(PlayerCareerStats.player_name == player_name)
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
                stats = PlayerCareerStats(
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
                    avg_series_per_season=avg_series,
                )
                session.add(stats)

    def update_totals(
        self,
        user_id: int,
        rating: int,
        series_won: int,
        series_lost: int,
        series_winrate: float,
        games_won: int,
        games_lost: int,
        games_winrate: float,
        seasons_played: int,
        avg_series: float,
    ) -> None:
        """Update combined total columns (from recalculation)"""
        with self.get_session() as session:
            stats = session.scalars(
                select(PlayerCareerStats)
                .where(PlayerCareerStats.user_id == user_id)
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

    def batch_update_stats(self, updates: list[dict[str, Any]]) -> dict[str, Any]:
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
        errors: list[str] = []

        for update_data in updates:
            user_id = update_data.get("user_id")
            try:
                with self.get_session() as session:
                    self._apply_stats_update(session, update_data)
                updated += 1
            except (SQLAlchemyError, KeyError) as e:
                # The error list goes to the client, so database errors stay fixed
                message = "Database error" if isinstance(e, SQLAlchemyError) else str(e)
                logger.exception(f"Error updating stats for user {user_id}")
                errors.append(f"Error for user {user_id}: {message}")

        return {"updated": updated, "errors": errors}

    def _apply_stats_update(
        self, session: OrmSession, update_data: dict[str, Any]
    ) -> None:
        """Create, link, or merge the stats record for one update item."""
        user_id = update_data["user_id"]
        player_name = update_data["player_name"]

        # Unmapped records have user_id=None
        record_by_user_id = None
        if user_id is not None:
            record_by_user_id = session.scalars(
                select(PlayerCareerStats)
                .where(PlayerCareerStats.user_id == user_id)
                .limit(1)
            ).first()
        record_by_name = session.scalars(
            select(PlayerCareerStats)
            .where(PlayerCareerStats.player_name == player_name)
            .limit(1)
        ).first()

        # Handle different scenarios
        if (
            record_by_user_id
            and record_by_name
            and record_by_user_id.id != record_by_name.id
        ):
            # Two separate records exist - merge historical into user_id record
            logger.info(
                f"Merging records for {player_name}: user_id record {record_by_user_id.id} and name record {record_by_name.id}"
            )
            stats_record = record_by_user_id
            # Keep existing player_name, don't overwrite with current name

            # Preserve historical data from the name-based record if it has any
            if record_by_name.historical_rating:
                stats_record.historical_rating = record_by_name.historical_rating
                stats_record.historical_series_won = (
                    record_by_name.historical_series_won
                )
                stats_record.historical_series_lost = (
                    record_by_name.historical_series_lost
                )
                stats_record.historical_games_won = record_by_name.historical_games_won
                stats_record.historical_games_lost = (
                    record_by_name.historical_games_lost
                )
                stats_record.historical_seasons_played = (
                    record_by_name.historical_seasons_played
                )

            # Delete the duplicate record
            session.delete(record_by_name)

        elif record_by_user_id:
            # Keep the historical player_name
            stats_record = record_by_user_id

        elif record_by_name:
            # Link the historical record to the user, keep its name
            stats_record = record_by_name
            stats_record.user_id = user_id

        else:
            # No existing record - create new with provided name
            stats_record = PlayerCareerStats(user_id=user_id, player_name=player_name)
            session.add(stats_record)

        # Update all stat fields
        stats_record.rating = update_data["rating"]
        stats_record.series_won = update_data["series_won"]
        stats_record.series_lost = update_data["series_lost"]
        stats_record.series_winrate = update_data["series_winrate"]
        stats_record.games_won = update_data["games_won"]
        stats_record.games_lost = update_data["games_lost"]
        stats_record.games_winrate = update_data["games_winrate"]
        stats_record.seasons_played = update_data["seasons_played"]
        stats_record.avg_series_per_season = update_data["avg_series_per_season"]

    def get_all_career_stats(
        self, limit: int | None = None, offset: int = 0
    ) -> tuple[list[PlayerCareerStatsPublic], int]:
        """Get all player career stats ordered by rating, and the total count"""
        return self.get_all(limit=limit, offset=offset)

    def get_career_stats_by_user(self, user_id: int) -> PlayerCareerStatsPublic | None:
        """Get career stats for a specific user"""
        return self.get_by_user_id(user_id)

    def import_historical_stats(
        self, csv_reader: Iterable[dict[str, str]]
    ) -> dict[str, Any]:
        """Import historical stats from CSV reader"""
        imported = 0
        skipped = 0
        errors: list[str] = []

        for row in csv_reader:
            try:
                player_name = row["NAME"].strip()

                # Parse stats
                rating = int(row["RATING"]) if row["RATING"] else 0
                series_won = int(row["WON Series"]) if row["WON Series"] else 0
                series_lost = int(row["LOST Series"]) if row["LOST Series"] else 0

                # Parse winrates (handle duplicate columns)
                values = list(row.values())
                keys = list(row.keys())
                winrate_indices = [i for i, k in enumerate(keys) if k == "WINRATE"]

                series_winrate = (
                    self._parse_percentage(values[winrate_indices[0]])
                    if len(winrate_indices) > 0
                    else 0.0
                )
                games_winrate = (
                    self._parse_percentage(values[winrate_indices[1]])
                    if len(winrate_indices) > 1
                    else 0.0
                )

                games_won = int(row["WON Games"]) if row["WON Games"] else 0
                games_lost = int(row["LOST Games"]) if row["LOST Games"] else 0
                seasons_played = (
                    int(row["Seasons PLAYED"]) if row["Seasons PLAYED"] else 0
                )
                avg_series = self._parse_avg_series(row.get("AVG NUM Series", "0"))

                # Each row runs as one short transaction
                self.update_historical_baseline(
                    player_name=player_name,
                    rating=rating,
                    series_won=series_won,
                    series_lost=series_lost,
                    games_won=games_won,
                    games_lost=games_lost,
                    seasons_played=seasons_played,
                    series_winrate=series_winrate,
                    games_winrate=games_winrate,
                    avg_series=avg_series,
                )

                imported += 1
                logger.info(f"Imported: {player_name} (Rating: {rating})")

            except Exception as e:
                logger.error(f"Error importing {row.get('NAME', 'Unknown')}: {e}")
                skipped += 1
                message = "Database error" if isinstance(e, SQLAlchemyError) else str(e)
                errors.append(
                    f"Error importing {row.get('NAME', 'Unknown')}: {message}"
                )

        return {"imported": imported, "skipped": skipped, "errors": errors}

    def _parse_percentage(self, value: str | None) -> float:
        """Parse percentage string like '75 %' to decimal like 75.00"""
        if not value or value == "0 %":
            return 0.0
        return float(value.replace(" %", "").replace("%", ""))

    def _parse_avg_series(self, value: str | None) -> float:
        """Parse avg series string like '4,0' to decimal 4.0"""
        if not value:
            return 0.0
        clean = value.strip('"').replace(",", ".")
        return float(clean)

    def recalculate_all_stats(self) -> dict[str, Any]:
        """
        Recalculate career stats for all players by combining:
        1. Historical baseline (if exists)
        2. Current stats from ALL series data in the database

        Only processes players who have played at least one series.
        Always uses all stored series to ensure accurate career totals.
        Returns summary of updated players.
        """
        # Ids, scores, season and player names, one row per series
        all_series = self.series_service.career_stats_rows()

        # Get all unique seasons in the system (for proper decay calculation)
        all_system_seasons = set()
        for series in all_series:
            if series.season_id:
                all_system_seasons.add(series.season_id)
        all_system_seasons = sorted(all_system_seasons)  # Sort in ascending order

        # Group series by player and collect user info
        series_by_player = {}
        player_names = {}  # Store player names from the series

        for series in all_series:
            player1_id = series.player1_id
            player2_id = series.player2_id

            if player1_id:
                if player1_id not in series_by_player:
                    series_by_player[player1_id] = []
                    if series.player1_name:
                        player_names[player1_id] = series.player1_name
                series_by_player[player1_id].append(series)

            if player2_id:
                if player2_id not in series_by_player:
                    series_by_player[player2_id] = []
                    if series.player2_name:
                        player_names[player2_id] = series.player2_name
                series_by_player[player2_id].append(series)

        # Prepare updates list
        updates = []

        # Get all existing stats records upfront (more efficient than querying per player)
        with self.get_session() as session:
            all_existing_stats = self._stored_rows(session)

        # Create lookup dictionaries for fast access
        stats_by_user_id = {
            stat.user_id: stat for stat in all_existing_stats if stat.user_id
        }
        stats_by_name = {
            stat.player_name: stat for stat in all_existing_stats if stat.player_name
        }

        # Track which stats we've processed (to identify historical-only players at the end)
        processed_stat_ids = set()

        # Process each player who has played series
        for user_id, user_series in series_by_player.items():
            # Get player name from series data
            player_name = player_names.get(user_id, "Unknown")

            # Look for existing stats in our in-memory lookup (no DB query)
            existing_stats = stats_by_user_id.get(user_id)

            # If not found by user_id, search by player_name to find unmapped historical records
            if not existing_stats:
                existing_stats = stats_by_name.get(player_name)
                if existing_stats:
                    logger.info(
                        f"Found unmapped historical record for '{player_name}', linking to user_id {user_id}"
                    )

            # Mark this stat as processed
            if existing_stats:
                processed_stat_ids.add(existing_stats.id)

            # Use existing player_name if record exists (preserves historical name)
            if existing_stats and existing_stats.player_name:
                player_name = existing_stats.player_name

            # Get historical baseline (preserved from CSV import)
            historical_baseline = {
                "rating": 0,
                "series_won": 0,
                "series_lost": 0,
                "games_won": 0,
                "games_lost": 0,
                "seasons_played": 0,
            }

            if existing_stats:
                historical_baseline = {
                    "rating": existing_stats.historical_rating or 0,
                    "series_won": existing_stats.historical_series_won or 0,
                    "series_lost": existing_stats.historical_series_lost or 0,
                    "games_won": existing_stats.historical_games_won or 0,
                    "games_lost": existing_stats.historical_games_lost or 0,
                    "seasons_played": existing_stats.historical_seasons_played or 0,
                }

            # Calculate current stats from series data
            current_stats = self._calculate_player_stats_from_series(
                user_id, user_series
            )

            # Combine historical + current for totals
            total_series_won = (
                historical_baseline["series_won"] + current_stats["series_won"]
            )
            total_series_lost = (
                historical_baseline["series_lost"] + current_stats["series_lost"]
            )
            total_games_won = (
                historical_baseline["games_won"] + current_stats["games_won"]
            )
            total_games_lost = (
                historical_baseline["games_lost"] + current_stats["games_lost"]
            )

            # Calculate winrates
            total_series = total_series_won + total_series_lost
            series_winrate = (
                (total_series_won / total_series * 100) if total_series > 0 else 0.0
            )

            total_games = total_games_won + total_games_lost
            games_winrate = (
                (total_games_won / total_games * 100) if total_games > 0 else 0.0
            )

            # Get unique seasons played
            seasons_in_data = len({s.season_id for s in user_series if s.season_id})
            total_seasons = historical_baseline["seasons_played"] + seasons_in_data

            # Calculate avg series per season
            avg_series = total_series / total_seasons if total_seasons > 0 else 0.0

            # All system seasons are passed so inactive players still decay
            final_rating = self._calculate_gnl_rating(
                user_id, user_series, historical_baseline["rating"], all_system_seasons
            )
            logger.debug(
                f"Calculated GNL rating for user {user_id} ({player_name}): {final_rating}"
            )
            # Add to updates
            updates.append(
                {
                    "user_id": user_id,
                    "player_name": player_name,
                    "rating": final_rating,
                    "series_won": total_series_won,
                    "series_lost": total_series_lost,
                    "series_winrate": round(series_winrate, 2),
                    "games_won": total_games_won,
                    "games_lost": total_games_lost,
                    "games_winrate": round(games_winrate, 2),
                    "seasons_played": total_seasons,
                    "avg_series_per_season": round(avg_series, 2),
                }
            )

        # Historical-only players: stats records with no matching series
        for historical_stat in all_existing_stats:
            # Skip if we already processed this stat record
            if historical_stat.id in processed_stat_ids:
                continue

            # Skip if no historical data at all
            has_historical_data = (
                (
                    historical_stat.historical_rating
                    and historical_stat.historical_rating > 0
                )
                or (
                    historical_stat.historical_series_won
                    and historical_stat.historical_series_won > 0
                )
                or (
                    historical_stat.historical_series_lost
                    and historical_stat.historical_series_lost > 0
                )
                or (
                    historical_stat.historical_games_won
                    and historical_stat.historical_games_won > 0
                )
                or (
                    historical_stat.historical_games_lost
                    and historical_stat.historical_games_lost > 0
                )
                or (
                    historical_stat.historical_seasons_played
                    and historical_stat.historical_seasons_played > 0
                )
            )
            if not has_historical_data:
                continue

            # Historical data and no current series, so decay only
            decayed_rating = self._calculate_gnl_rating(
                user_id=historical_stat.user_id,
                series_list=[],  # No series played
                historical_rating=historical_stat.historical_rating,
                all_system_seasons=all_system_seasons,
            )
            logger.debug(
                f"Decayed historical rating for user {historical_stat.user_id} ({historical_stat.player_name}): {decayed_rating}"
            )

            # Use historical values for stats (they don't change, just decay the rating)
            historical_series_won = historical_stat.historical_series_won or 0
            historical_series_lost = historical_stat.historical_series_lost or 0
            historical_games_won = historical_stat.historical_games_won or 0
            historical_games_lost = historical_stat.historical_games_lost or 0

            # Calculate winrates from historical data
            total_series = historical_series_won + historical_series_lost
            series_winrate = (
                (historical_series_won / total_series * 100)
                if total_series > 0
                else 0.0
            )

            total_games = historical_games_won + historical_games_lost
            games_winrate = (
                (historical_games_won / total_games * 100) if total_games > 0 else 0.0
            )

            # Calculate avg series per season
            seasons_played = historical_stat.historical_seasons_played or 0
            avg_series = total_series / seasons_played if seasons_played > 0 else 0.0

            updates.append(
                {
                    "user_id": historical_stat.user_id,
                    "player_name": historical_stat.player_name,
                    "rating": decayed_rating,
                    "series_won": historical_series_won,
                    "series_lost": historical_series_lost,
                    "series_winrate": round(series_winrate, 2),
                    "games_won": historical_games_won,
                    "games_lost": historical_games_lost,
                    "games_winrate": round(games_winrate, 2),
                    "seasons_played": seasons_played,
                    "avg_series_per_season": round(avg_series, 2),
                }
            )

        # Batch update
        result = self.batch_update_stats(updates)

        logger.info(f"Recalculated stats for {result['updated']} players")
        return result

    def _calculate_player_stats_from_series(
        self, user_id: int, series_list: list[CareerSeriesRow]
    ) -> dict[str, Any]:
        """Calculate stats for a player from their series records"""
        series_won = 0
        series_lost = 0
        games_won = 0
        games_lost = 0

        for series in series_list:
            # Determine if player won or lost series
            if series.player1_id == user_id:
                player_score = series.player1_score or 0
                opponent_score = series.player2_score or 0
            else:
                player_score = series.player2_score or 0
                opponent_score = series.player1_score or 0

            # Skip series with no scores (not played yet)
            if player_score == 0 and opponent_score == 0:
                continue

            if player_score > opponent_score:
                series_won += 1
            elif opponent_score > player_score:
                series_lost += 1

            # Add game counts
            games_won += player_score
            games_lost += opponent_score

        return {
            "series_won": series_won,
            "series_lost": series_lost,
            "games_won": games_won,
            "games_lost": games_lost,
        }

    def _calculate_gnl_rating(
        self,
        user_id: int,
        series_list: list[CareerSeriesRow],
        historical_rating: float = 0,
        all_system_seasons: list[int] | None = None,
    ) -> int:
        """Calculate GNL Rating from series records.

        GNL Rating rewards participation and performance with decay for older seasons.
        Starts with historical_rating (if provided) which also decays as we move through seasons.
        Decay is applied for ALL seasons in the system, even if player didn't participate.

        Args:
            user_id: Player's user ID
            series_list: The series rows of this player
            historical_rating: Historical baseline rating (already multiplied by 100)
            all_system_seasons: List of all season IDs in the system (sorted)

        Formula:
        - Match win: +GNL_RATING_MATCH_WIN_VALUE
        - Match loss: +GNL_RATING_MATCH_LOSS_VALUE
        - Season participation: +GNL_RATING_SEASON_PLAYED_VALUE
        - Every season applies decay: GNL_RATING_DECAY_RATE_PER_SEASON
        """
        if not all_system_seasons:
            all_system_seasons = []

        if not series_list and historical_rating == 0:
            return 0

        # Group series by season
        series_by_season = {}
        for series in series_list:
            if series.season_id:
                season_id = series.season_id
                if season_id not in series_by_season:
                    series_by_season[season_id] = []
                series_by_season[season_id].append(series)

        # Calculate rating per season (only for seasons with series)
        rating_by_season = {}
        if series_by_season:
            # Season ids increment, so sorting them gives the decay order
            seasons = sorted(series_by_season.keys())

            for season_id in seasons:
                season_rating = 0
                for series in series_by_season[season_id]:
                    # Determine if this was a win or loss
                    is_victory = False
                    player_score = 0
                    opponent_score = 0

                    if series.player1_id == user_id:
                        player_score = series.player1_score or 0
                        opponent_score = series.player2_score or 0
                        is_victory = player_score > opponent_score
                    elif series.player2_id == user_id:
                        player_score = series.player2_score or 0
                        opponent_score = series.player1_score or 0
                        is_victory = player_score > opponent_score

                    # Skip series with no scores (not played yet)
                    if player_score == 0 and opponent_score == 0:
                        continue

                    match_rating = (
                        GNL_RATING_MATCH_WIN_VALUE
                        if is_victory
                        else GNL_RATING_MATCH_LOSS_VALUE
                    )
                    season_rating += match_rating

                rating_by_season[season_id] = season_rating

        # The stored historical rating is scaled, so divide it back to raw points
        gnl_rating = (
            historical_rating / GNL_RATING_FLAT_MULTIPLIER
            if historical_rating > 0
            else 0
        )

        # Every season decays every player, including historical-only ones
        for season_id in all_system_seasons:
            gnl_rating *= 1.0 - GNL_RATING_DECAY_RATE_PER_SEASON

            # Add this season's rating if player participated
            if season_id in rating_by_season:
                season_rating = rating_by_season[season_id]
                gnl_rating += season_rating

                # Bonus for playing in this season
                if season_rating > 0:
                    gnl_rating += GNL_RATING_SEASON_PLAYED_VALUE

        # Apply multiplier to final rating
        gnl_rating *= GNL_RATING_FLAT_MULTIPLIER

        return int(gnl_rating)

    def update_career_stats(
        self, stat_id: int, stats: PlayerCareerStatsPublic
    ) -> PlayerCareerStatsPublic | None:
        """Update career stats (historical values and user link)"""
        with self.get_session() as session:
            updated_stat = PlayerCareerStats.update(
                session, stat_id, **stats.model_dump(exclude_unset=True)
            )
            if not updated_stat:
                return None

            public = PlayerCareerStatsPublic.from_career_stats(updated_stat)
            derived.fill_career(session, [public])
            return public

    def delete_career_stats(self, stat_id: int) -> bool:
        """Delete career stats record"""
        stat = self.get(stat_id)
        if not stat:
            return False

        self.delete(stat_id)
        return True
