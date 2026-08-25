import logging
import os
import urllib.parse
from typing import TYPE_CHECKING, Any

import requests

from app.core.exceptions import BadRequestError, NotFoundError
from app.models.enums import Race
from app.models.w3c_stats import W3CStatsCreate

if TYPE_CHECKING:
    from app.services.settings import SettingsService

logger = logging.getLogger(__name__)

# Seconds a w3champions call can hold the thread before it fails.
REQUEST_TIMEOUT = 10

# The w3champions API base, used when neither the setting nor the environment names one.
DEFAULT_BASE_URL = "https://website-backend.w3champions.com/api"


class W3CService:
    def __init__(self, settings_app_service: "SettingsService | None" = None) -> None:
        self.settings_app_service = settings_app_service

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"

    def _setting(self, key: str) -> str | None:
        """A settings value, or None when the row is absent."""
        if not self.settings_app_service:
            return None
        try:
            setting = self.settings_app_service.get_setting(key)
        except NotFoundError:
            return None
        return setting.get("value") if setting else None

    def base_url(self) -> str:
        """The w3champions API base: the setting, then the environment, then the default."""
        url = self._setting("w3c_url") or os.getenv("W3C_URL") or DEFAULT_BASE_URL
        # Configuration written before the base URL split stored the players endpoint.
        return url.rstrip("/").removesuffix("/players")

    def latest_season(self) -> int:
        """The newest season w3champions lists."""
        seasons = self.send_request(
            method=self.GET, url=f"{self.base_url()}/ladder/seasons"
        )
        return max(int(season["id"]) for season in seasons)

    def current_season(self) -> int:
        """The configured season, or the newest one w3champions lists."""
        season = self._setting("current_wc3_season")
        return int(season) if season else self.latest_season()

    def validatePlayer(self, bnet_name: str) -> bool:
        """
        Validate that a player exists on W3Champions.
        Uses the /players endpoint which is simpler and doesn't require season info.
        Returns True if player exists, False otherwise.
        """
        if not isinstance(bnet_name, str):
            raise ValueError("bnet_name must be a string")

        try:
            result = self.send_request(
                method=self.GET,
                url=f"{self.base_url()}/players/{urllib.parse.quote(bnet_name)}",
            )
            # If we get a successful response, the player exists
            return result is not None
        except Exception as e:
            logger.debug(f"Player validation failed for {bnet_name}: {e!s}")
            return False

    def getPlayerStats(
        self, bnet_name: str, season_override: int | None = None
    ) -> list[W3CStatsCreate]:
        if not isinstance(bnet_name, str):
            raise ValueError("bnet_name must be a string")

        season_to_fetch = (
            season_override if season_override is not None else self.current_season()
        )

        param = {"gateWay": 20, "season": season_to_fetch}
        result = self.send_request(
            method=self.GET,
            url=f"{self.base_url()}/players/{urllib.parse.quote(bnet_name)}/game-mode-stats",
            params=param,
        )
        if not result:
            logger.debug(f"no stats found for player {bnet_name} on w3c")
            raise BadRequestError(f"No stats found for player {bnet_name} on W3C")
        stats: list[W3CStatsCreate] = []
        for gmode_stats in result:
            if gmode_stats.get("gameMode") and gmode_stats.get("gameMode") == 1:
                stats.append(
                    W3CStatsCreate(
                        wc3_season=gmode_stats.get("season"),
                        wins=gmode_stats.get("wins"),
                        losses=gmode_stats.get("losses"),
                        games=gmode_stats.get("games"),
                        mmr=gmode_stats.get("mmr"),
                        winrate=gmode_stats.get("winrate"),
                        race=self.getRaceEnum(gmode_stats.get("race")),
                        league=gmode_stats.get("leagueOrder"),
                    )
                )
        return stats

    def getRaceEnum(self, race_int: int | None) -> Race | None:
        if race_int is None:
            return None
        race_mapping = {0: Race.RANDOM, 8: Race.UD, 1: Race.HU, 4: Race.NE, 2: Race.OC}
        race = race_mapping.get(race_int)
        return race

    def send_request(
        self,
        method: str,
        url: str,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:  # noqa: ANN401  # the w3champions body has no fixed shape
        try:
            # Send the request
            response = requests.request(
                method,
                url,
                json=data,
                headers=headers,
                params=params,
                timeout=REQUEST_TIMEOUT,
            )

            # Check the status code
            if response.status_code in [200, 201]:
                try:
                    return response.json()  # Parse JSON response
                except ValueError:
                    raise Exception(response.text)  # Return plain text if not JSON
            if response.status_code == 204:
                return response.text
            else:
                # Log or raise an error for non-200 status codes
                raise Exception(
                    f"Request failed with status code {response.status_code}: {response.text}"
                )

        except requests.exceptions.RequestException as e:
            # Handle network-related errors
            raise Exception(f"An exception occurred: {e!s}")
