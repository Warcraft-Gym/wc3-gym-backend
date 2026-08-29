import logging
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core.db import Session
from app.core.ordering import SortOrder
from app.models.player_career_stats import (
    PlayerCareerStats,
    PlayerCareerStatsPublic,
)
from app.models.user import User
from app.services import derived
from app.services.derived import CareerSort

logger = logging.getLogger(__name__)


class PlayerCareerStatsService:
    def get(self, stat_id: int) -> PlayerCareerStatsPublic | None:
        """Get career stats by stats record ID (implements abstract method)"""
        with Session.begin() as session:
            stat = session.get(
                PlayerCareerStats, stat_id, options=PlayerCareerStats.eager_options()
            )
            if not stat:
                return None
            public = PlayerCareerStatsPublic.from_career_stats(stat)
            derived.fill_career(session, [public])
            return public

    def delete(self, stat_id: int) -> bool:
        """Delete career stats by stats ID (implements abstract method)"""
        with Session.begin() as session:
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
                .order_by(col(PlayerCareerStats.id))
            )
            .unique()
            .all()
        )
        return [PlayerCareerStatsPublic.from_career_stats(stat) for stat in stats]

    def get_all(
        self,
        limit: int | None = None,
        offset: int = 0,
        search: str = "",
        *,
        sort: CareerSort | None = None,
        order: SortOrder = "asc",
    ) -> tuple[list[PlayerCareerStatsPublic], int]:
        """The career stats by rating, or one page of them, and the total count

        The rating orders the rows and the id breaks a tie, so offset paging
        walks a fixed order. search keeps the rows whose player name or user
        name holds it, so the page and the count hold to the kept rows.

        sort names a key of derived.CAREER_SORTS and orders the rows by it.
        """
        with Session.begin() as session:
            rows = derived.career_rows(
                session, self._stored_rows(session), search, sort=sort, order=order
            )
            end = None if limit is None else offset + limit
            return rows[offset:end], len(rows)

    def get_by_user_id(self, user_id: int) -> PlayerCareerStatsPublic | None:
        """Get career stats for a specific user"""
        with Session.begin() as session:
            stat = session.scalars(
                select(PlayerCareerStats)
                .options(*PlayerCareerStats.eager_options())
                .where(col(PlayerCareerStats.user_id) == user_id)
                .limit(1)
            ).first()
            if not stat:
                return None
            public = PlayerCareerStatsPublic.from_career_stats(stat)
            derived.fill_career(session, [public])
            return public

    def update_historical_baseline(
        self,
        player_name: str,
        rating: int,
        series_won: int,
        series_lost: int,
        games_won: int,
        games_lost: int,
        seasons_played: int,
    ) -> None:
        """Update historical baseline columns (from CSV import).

        Resolves the user by player name in the same transaction, so one
        CSV row is one short transaction.
        """
        with Session.begin() as session:
            user = session.scalars(
                select(User).where(col(User.name) == player_name).limit(1)
            ).first()
            user_id = user.id if user else None
            if not user:
                logger.info(
                    f"User not found for {player_name}, importing anyway with null user_id"
                )

            # Find by player_name first
            stats = session.scalars(
                select(PlayerCareerStats)
                .where(col(PlayerCareerStats.player_name) == player_name)
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
                )
                session.add(stats)

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
                games_won = int(row["WON Games"]) if row["WON Games"] else 0
                games_lost = int(row["LOST Games"]) if row["LOST Games"] else 0
                seasons_played = (
                    int(row["Seasons PLAYED"]) if row["Seasons PLAYED"] else 0
                )

                # Each row runs as one short transaction
                self.update_historical_baseline(
                    player_name=player_name,
                    rating=rating,
                    series_won=series_won,
                    series_lost=series_lost,
                    games_won=games_won,
                    games_lost=games_lost,
                    seasons_played=seasons_played,
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

    def update_career_stats(
        self, stat_id: int, stats: PlayerCareerStatsPublic
    ) -> PlayerCareerStatsPublic | None:
        """Update career stats (historical values and user link)"""
        with Session.begin() as session:
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
