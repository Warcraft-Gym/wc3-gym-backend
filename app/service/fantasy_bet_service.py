from app.database.fantasy_bet_db_service import FantasyBetDBService
from app.exceptions import NotFoundException
from app.schemas.fantasy_bet import FantasyBet


class FantasyBetAppService:
    def __init__(
        self, fantasy_bet_service: FantasyBetDBService, settings_app_service=None
    ):
        self.fantasy_bet_service = fantasy_bet_service
        self.settings_app_service = settings_app_service

    def _apply_bet_points_logic(self, bet: FantasyBet):
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
                except (NotFoundException, Exception):
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
                except (NotFoundException, Exception):
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

        except NotFoundException:
            # Settings don't exist, require bet_points from input
            if bet.bet_points is None or bet.bet_points <= 0:
                raise ValueError("bet_points is required and must be greater than 0")

    def create_fantasy_bet(self, bet: FantasyBet):
        self._apply_bet_points_logic(bet)
        bet.id = None
        bet_data = self.fantasy_bet_service.add(bet)
        return bet_data

    def update_fantasy_bet(self, bet_id: int, bet: FantasyBet):
        self._apply_bet_points_logic(bet)
        bet.id = bet_id
        bet_data = self.fantasy_bet_service.update(bet)
        return bet_data

    def delete_fantasy_bet(self, bet_id: int):
        self.fantasy_bet_service.delete(bet_id)

    def get_fantasy_bet(self, bet_id: int):
        bet_data = self.fantasy_bet_service.get(bet_id)
        if not bet_data:
            raise NotFoundException(f"Fantasy Bet not found by Id: {bet_id}")
        return bet_data

    def getAll_fantasy_bets(self):
        bet_data = self.fantasy_bet_service.getAll()
        return bet_data

    def search_fantasy_bets(self, query):
        bet_data = self.fantasy_bet_service.search(query)
        return bet_data
