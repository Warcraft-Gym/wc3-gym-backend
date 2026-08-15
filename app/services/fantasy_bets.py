import logging
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.exceptions import NotFoundError
from app.models.fantasy_bet import (
    FantasyBet,
    FantasyBetCreate,
    FantasyBetPublic,
    FantasyBetUpdate,
)
from app.models.series import Series
from app.services.base import BaseService
from app.utils.query_util import QueryElement, QueryUtil

if TYPE_CHECKING:
    from app.services.settings import SettingsService

logger = logging.getLogger(__name__)


class FantasyBetService(BaseService):
    def __init__(self, settings_app_service: "SettingsService | None" = None) -> None:
        self.settings_app_service = settings_app_service

    def add(self, fantasy_bet: FantasyBetCreate) -> FantasyBetPublic:
        with self.get_session() as session:
            fbet = FantasyBet.add(session, fantasy_bet.model_dump())
            return FantasyBetPublic.from_fantasy_bet(fbet)

    def update(
        self, fantasy_bet_id: int, fantasy_bet: FantasyBetUpdate
    ) -> FantasyBetPublic:
        with self.get_session() as session:
            fantasy_bet = FantasyBet.update(
                session,
                fantasy_bet_id,
                **fantasy_bet.model_dump(exclude_unset=True),
            )
            if not fantasy_bet:
                raise NotFoundError("Fantasy Bet not found")
            return FantasyBetPublic.from_fantasy_bet(fantasy_bet)

    def delete(self, fantasy_bet_id: int) -> None:
        with self.get_session() as session:
            FantasyBet.delete(session, fantasy_bet_id)

    def get(self, fantasy_bet_id: int) -> FantasyBetPublic:
        with self.get_session() as session:
            fbet = session.get(FantasyBet, fantasy_bet_id)
            if not fbet:
                raise NotFoundError("Fantasy Bet not found")
            return FantasyBetPublic.from_fantasy_bet(fbet)

    def getAll(self) -> list[FantasyBetPublic]:
        with self.get_session() as session:
            result = []
            fbet = FantasyBet.getAll(session)
            for single_fbet in fbet:
                result.append(FantasyBetPublic.from_fantasy_bet(single_fbet))
            return result

    def search(self, query: QueryElement | None) -> list[FantasyBetPublic]:
        with self.get_session() as session:
            result = []
            filter = QueryUtil.convertQueryToDBFilter(FantasyBet, query)
            if filter is None:
                logger.debug(f"No fantasy bets found by searchcriteria: {query}")
                return result
            # Eager load the relations that the DTO and the score service read.
            # noload('*') stops all other relations from loading, so every
            # relation that a caller reads must be listed here. The score
            # breakdown reads series.match.playday.
            fbets = (
                session.scalars(
                    select(FantasyBet)
                    .options(
                        joinedload(FantasyBet.season).noload("*"),
                        joinedload(FantasyBet.user).noload("*"),
                        joinedload(FantasyBet.winner).noload("*"),
                        joinedload(FantasyBet.series).noload("*"),
                        joinedload(FantasyBet.series)
                        .joinedload(Series.player1)
                        .noload("*"),
                        joinedload(FantasyBet.series)
                        .joinedload(Series.player2)
                        .noload("*"),
                        joinedload(FantasyBet.series)
                        .joinedload(Series.match)
                        .noload("*"),
                    )
                    .where(filter)
                )
                .unique()
                .all()
            )
            if not fbets:
                logger.debug(f"No fantasy bets found by searchcriteria: {query}")
                return result
            for fbet in fbets:
                result.append(FantasyBetPublic.from_fantasy_bet(fbet))
            return result

    def _apply_bet_points_logic(self, bet: FantasyBetCreate | FantasyBetUpdate) -> None:
        """Apply bet points based on settings: use fixed points or validate user input."""
        if not self.settings_app_service:
            # If no settings service, require bet_points from input
            if bet.bet_points is None or bet.bet_points <= 0:
                raise ValueError("bet_points is required and must be greater than 0")
            return

        try:
            # Check if fixed bet points are enabled
            fixed_bet_points_setting = self.settings_app_service.get_setting(
                "fantasy_fixed_bet_points"
            )
            use_fixed_points = (
                fixed_bet_points_setting
                and fixed_bet_points_setting.get("value", "").lower() == "true"
            )

            if use_fixed_points:
                # Use the fixed bet points value from settings
                bet_points_value_setting = self.settings_app_service.get_setting(
                    "fantasy_bet_points_value"
                )
                if not bet_points_value_setting or not bet_points_value_setting.get(
                    "value"
                ):
                    raise ValueError(
                        "Fixed bet points enabled but fantasy_bet_points_value is not configured"
                    )

                bet.bet_points = int(bet_points_value_setting.get("value"))
            else:
                # Validate that bet_points were provided from UI
                if bet.bet_points is None or bet.bet_points <= 0:
                    raise ValueError(
                        "bet_points is required when fixed bet points is disabled"
                    )

                # Validate min/max bet points only if they are defined and different
                try:
                    min_bet_setting = self.settings_app_service.get_setting(
                        "fantasy_min_bet_points"
                    )
                    min_bet = (
                        int(min_bet_setting.get("value"))
                        if min_bet_setting and min_bet_setting.get("value")
                        else None
                    )
                except (NotFoundError, Exception):
                    min_bet = None

                try:
                    max_bet_setting = self.settings_app_service.get_setting(
                        "fantasy_max_bet_points"
                    )
                    max_bet = (
                        int(max_bet_setting.get("value"))
                        if max_bet_setting and max_bet_setting.get("value")
                        else None
                    )
                except (NotFoundError, Exception):
                    max_bet = None

                # Only validate if min and max are both defined and different
                if min_bet is not None and max_bet is not None and min_bet != max_bet:
                    if bet.bet_points < min_bet:
                        raise ValueError(f"bet_points must be at least {min_bet}")

                    if bet.bet_points > max_bet:
                        raise ValueError(f"bet_points must not exceed {max_bet}")
                elif min_bet is not None and max_bet is None:
                    # Only min is defined
                    if bet.bet_points < min_bet:
                        raise ValueError(f"bet_points must be at least {min_bet}")
                elif max_bet is not None and min_bet is None:
                    # Only max is defined
                    if bet.bet_points > max_bet:
                        raise ValueError(f"bet_points must not exceed {max_bet}")

        except NotFoundError:
            # Settings don't exist, require bet_points from input
            if bet.bet_points is None or bet.bet_points <= 0:
                raise ValueError("bet_points is required and must be greater than 0")

    def create_fantasy_bet(self, bet: FantasyBetCreate) -> FantasyBetPublic:
        self._apply_bet_points_logic(bet)
        return self.add(bet)

    def update_fantasy_bet(
        self, bet_id: int, bet: FantasyBetUpdate
    ) -> FantasyBetPublic:
        self._apply_bet_points_logic(bet)
        return self.update(bet_id, bet)

    def delete_fantasy_bet(self, bet_id: int) -> None:
        self.delete(bet_id)

    def get_fantasy_bet(self, bet_id: int) -> FantasyBetPublic:
        bet_data = self.get(bet_id)
        if not bet_data:
            raise NotFoundError(f"Fantasy Bet not found by Id: {bet_id}")
        return bet_data

    def getAll_fantasy_bets(self) -> list[FantasyBetPublic]:
        return self.getAll()

    def search_fantasy_bets(self, query: QueryElement | None) -> list[FantasyBetPublic]:
        return self.search(query)
