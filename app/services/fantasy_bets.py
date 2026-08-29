import logging
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import joinedload
from sqlmodel import col

from app.core.db import Session
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.ordering import SortOrder, ordered
from app.core.query import QueryElement, QueryUtil
from app.models.fantasy_bet import (
    FantasyBet,
    FantasyBetCreate,
    FantasyBetPublic,
    FantasyBetUpdate,
)
from app.models.series import Series
from app.models.user import User
from app.services import derived

if TYPE_CHECKING:
    from app.services.settings import SettingsService

logger = logging.getLogger(__name__)

BetSort = Literal["id", "bet_points", "captain", "series_id"]

# The names a bet list sorts by, and the column each one orders
BET_SORTS: dict[BetSort, ColumnElement[Any]] = {
    "id": FantasyBet.id,
    "bet_points": FantasyBet.bet_points,
    "captain": User.name,
    "series_id": FantasyBet.series_id,
}


FIXED_POINTS = "fantasy_fixed_bet_points"
POINTS_VALUE = "fantasy_bet_points_value"
MIN_POINTS = "fantasy_min_bet_points"
MAX_POINTS = "fantasy_max_bet_points"


def resolve_bet_points(settings: dict[str, str | None], points: int | None) -> int:
    """The points a bet is worth: the fixed value the settings name, or the
    value the caller sent inside the range they allow."""
    fixed = (settings.get(FIXED_POINTS) or "").lower() == "true"
    if fixed and POINTS_VALUE in settings:
        value = settings[POINTS_VALUE]
        if not value:
            raise BadRequestError(
                "Fixed bet points enabled but fantasy_bet_points_value is not configured"
            )
        return int(value)

    if FIXED_POINTS not in settings or fixed:
        # The settings name no points, so the value the caller sent stands
        if points is None or points <= 0:
            raise BadRequestError("bet_points is required and must be greater than 0")
        return points

    if points is None or points <= 0:
        raise BadRequestError(
            "bet_points is required when fixed bet points is disabled"
        )
    minimum = _points_setting(settings, MIN_POINTS)
    maximum = _points_setting(settings, MAX_POINTS)
    if minimum == maximum:
        return points
    if minimum is not None and points < minimum:
        raise BadRequestError(f"bet_points must be at least {minimum}")
    if maximum is not None and points > maximum:
        raise BadRequestError(f"bet_points must not exceed {maximum}")
    return points


def _points_setting(settings: dict[str, str | None], key: str) -> int | None:
    """A bound on the points of a bet, or None when the settings hold none."""
    value = settings.get(key)
    return int(value) if value else None


class FantasyBetService:
    def __init__(self, settings_app_service: "SettingsService | None" = None) -> None:
        self.settings_app_service = settings_app_service

    def add(self, fantasy_bet: FantasyBetCreate) -> FantasyBetPublic:
        with Session.begin() as session:
            fbet = FantasyBet.add(session, fantasy_bet.model_dump())
            public = FantasyBetPublic.from_fantasy_bet(fbet)
            derived.fill_series(session, [public.series])
            derived.fill_bet_results([public])
            return public

    def update(
        self, fantasy_bet_id: int, fantasy_bet: FantasyBetUpdate
    ) -> FantasyBetPublic:
        with Session.begin() as session:
            fantasy_bet = FantasyBet.update(
                session,
                fantasy_bet_id,
                **fantasy_bet.model_dump(exclude_unset=True),
            )
            if not fantasy_bet:
                raise NotFoundError("Fantasy Bet not found")
            public = FantasyBetPublic.from_fantasy_bet(fantasy_bet)
            derived.fill_series(session, [public.series])
            derived.fill_bet_results([public])
            return public

    def delete(self, fantasy_bet_id: int) -> None:
        with Session.begin() as session:
            FantasyBet.delete(session, fantasy_bet_id)

    def get(self, fantasy_bet_id: int) -> FantasyBetPublic:
        with Session.begin() as session:
            fbet = session.get(
                FantasyBet, fantasy_bet_id, options=FantasyBet.eager_options()
            )
            if not fbet:
                raise NotFoundError("Fantasy Bet not found")
            public = FantasyBetPublic.from_fantasy_bet(fbet)
            derived.fill_series(session, [public.series])
            derived.fill_bet_results([public])
            return public

    def get_all(
        self, limit: int | None = None, offset: int = 0
    ) -> tuple[list[FantasyBetPublic], int | None]:
        """The bets and, when a page is asked for, the total count."""
        with Session.begin() as session:
            statement = select(FantasyBet).options(*FantasyBet.list_eager_options())
            total = None
            if limit is not None or offset:
                # Offset paging is deterministic only with a fixed order
                total = session.scalar(select(func.count()).select_from(FantasyBet))
                statement = statement.order_by(col(FantasyBet.id)).offset(offset)
                if limit is not None:
                    statement = statement.limit(limit)
            result = []
            fbet = session.scalars(statement).unique().all()
            for single_fbet in fbet:
                result.append(FantasyBetPublic.from_fantasy_bet_reduced(single_fbet))
            derived.fill_series(session, [bet.series for bet in result])
            derived.fill_bet_results(result)
            return result, total

    def search(
        self,
        query: QueryElement | None,
        limit: int | None = None,
        offset: int = 0,
        *,
        sort: BetSort | None = None,
        order: SortOrder = "asc",
    ) -> tuple[list[FantasyBetPublic], int | None]:
        """The matching bets and, when a page is asked for, the total count.

        sort names a column of BET_SORTS and the bet id breaks its ties.
        """
        with Session.begin() as session:
            result = []
            filter = QueryUtil.convert_query_to_db_filter(FantasyBet, query)
            if filter is None:
                logger.debug(f"No fantasy bets found by searchcriteria: {query}")
                return result, None
            total = None
            statement = (
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
                    joinedload(FantasyBet.series).joinedload(Series.match).noload("*"),
                )
                .where(filter)
            )
            if limit is not None or offset:
                # Offset paging is deterministic only with a fixed order
                total = session.scalar(
                    select(func.count()).select_from(FantasyBet).where(filter)
                )
                if sort == "captain":
                    # A bet links to users twice, so the join names its own condition
                    statement = statement.join(User, col(User.id) == FantasyBet.user_id)
                statement = ordered(
                    statement, BET_SORTS, sort, order, col(FantasyBet.id)
                ).offset(offset)
                if limit is not None:
                    statement = statement.limit(limit)
            fbets = session.scalars(statement).unique().all()
            if not fbets:
                logger.debug(f"No fantasy bets found by searchcriteria: {query}")
                return result, total
            for fbet in fbets:
                result.append(FantasyBetPublic.from_fantasy_bet(fbet))
            derived.fill_series(session, [bet.series for bet in result])
            derived.fill_bet_results(result)
            return result, total

    def _apply_bet_points_logic(self, bet: FantasyBetCreate | FantasyBetUpdate) -> None:
        """Fill in the points the settings decide."""
        settings = (
            self.settings_app_service.get_settings_dict()
            if self.settings_app_service
            else {}
        )
        bet.bet_points = resolve_bet_points(settings, bet.bet_points)

    def create_fantasy_bet(self, bet: FantasyBetCreate) -> FantasyBetPublic:
        self._apply_bet_points_logic(bet)
        return self.add(bet)

    def update_fantasy_bet(
        self, bet_id: int, bet: FantasyBetUpdate
    ) -> FantasyBetPublic:
        # model_fields_set separates an absent field from an explicit null
        if "bet_points" in bet.model_fields_set:
            self._apply_bet_points_logic(bet)
        return self.update(bet_id, bet)
