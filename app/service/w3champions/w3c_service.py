import logging
import os
import urllib.parse

import requests

from app.models.enums import Race
from app.schemas.w3c_stats import W3CStats

logger = logging.getLogger(__name__)


class W3CService:
    def __init__(self, settings_app_service=None):
        self.settings_app_service = settings_app_service

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"

    def validatePlayer(self, bnet_name):
        """
        Validate that a player exists on W3Champions.
        Uses the /api/players endpoint which is simpler and doesn't require season info.
        Returns True if player exists, False otherwise.
        """
        if not isinstance(bnet_name, str):
            raise ValueError("bnet_name must be a string")

        # Get W3C URL from database or environment
        w3c_url = None
        if self.settings_app_service:
            w3c_url_setting = self.settings_app_service.get_setting("w3c_url")
            w3c_url = w3c_url_setting.get("value") if w3c_url_setting else None

        # Fallback to environment variable if setting not available
        if not w3c_url:
            w3c_url = os.getenv("W3C_URL")

        if not w3c_url:
            raise ValueError(
                "w3c_url is required (not found in database or environment)"
            )

        try:
            result = self.send_request(
                method=self.GET, url=f"{w3c_url}/{urllib.parse.quote(bnet_name)}"
            )
            # If we get a successful response, the player exists
            return result is not None
        except Exception as e:
            logger.debug(f"Player validation failed for {bnet_name}: {e!s}")
            return False

    def getPlayerStats(self, bnet_name, season_override=None):
        if not isinstance(bnet_name, str):
            raise ValueError("bnet_name must be a string")

        # Get W3C configuration from database
        w3c_season = None
        w3c_url = None
        if self.settings_app_service:
            w3c_season_setting = self.settings_app_service.get_setting(
                "current_wc3_season"
            )
            w3c_url_setting = self.settings_app_service.get_setting("w3c_url")
            w3c_season = w3c_season_setting.get("value") if w3c_season_setting else None
            w3c_url = w3c_url_setting.get("value") if w3c_url_setting else None

        # Fallback to environment variables if settings not available
        if not w3c_season:
            w3c_season = os.getenv("CURRENT_WC3_SEASON")
        if not w3c_url:
            w3c_url = os.getenv("W3C_URL")

        if not w3c_season:
            raise ValueError(
                "w3c_season is required (not found in database or environment)"
            )
        if not w3c_url:
            raise ValueError(
                "w3c_url is required (not found in database or environment)"
            )

        # Use the override season if provided, otherwise use the configured current season
        season_to_fetch = season_override if season_override is not None else w3c_season

        param = {"gateWay": 20, "season": season_to_fetch}
        result = self.send_request(
            method=self.GET,
            url=f"{w3c_url}/{urllib.parse.quote(bnet_name)}/game-mode-stats",
            params=param,
        )
        if not result:
            logger.debug(f"no stats found for player {bnet_name} on w3c")
            raise Exception(f"No stats found for player {bnet_name} on W3C")
        stats = []
        for gmode_stats in result:
            if gmode_stats.get("gameMode") and gmode_stats.get("gameMode") == 1:
                stats.append(
                    W3CStats(
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

    def getRaceEnum(self, race_int):
        if race_int is None:
            return None
        race_mapping = {0: Race.RANDOM, 8: Race.UD, 1: Race.HU, 4: Race.NE, 2: Race.OC}
        race = race_mapping.get(race_int)
        return race

    def send_request(self, method, url, data=None, headers=None, params=None):
        try:
            # Send the request
            response = requests.request(
                method, url, json=data, headers=headers, params=params
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
