import requests
import os
import urllib.parse
import logging
from src.dtos.w3c_stats_dto import W3CStatsDTO
from src.database.model.DBEnums import Race


logger = logging.getLogger(__name__)

class W3CService:

    def __init__(self):
        pass

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"

    def getPlayerStats(self, bnet_name):
        if not isinstance(bnet_name, str):
            raise ValueError("bnet_name must be a string")
        w3c_season = os.getenv("CURRENT_WC3_SEASON")
        param = {
            'gateWay': 20,
            'season': w3c_season
        }
        w3c_url = os.getenv("W3C_URL")
        result =  self.send_request(method=self.GET, url=f"{w3c_url}/{urllib.parse.quote(bnet_name)}/game-mode-stats", params=param)
        if not result:
            logger.debug(f"no stats found for player {bnet_name} on w3c")
            return None
        stats = []
        for gmode_stats  in result:
            if gmode_stats.get('gameMode') and gmode_stats.get('gameMode') == 1:
                w3cstats = W3CStatsDTO(data={})
                w3cstats.wc3_season = gmode_stats.get('season')
                w3cstats.wins = gmode_stats.get('wins')
                w3cstats.losses = gmode_stats.get('losses')
                w3cstats.games = gmode_stats.get('games')
                w3cstats.mmr = gmode_stats.get('mmr')
                w3cstats.winrate = gmode_stats.get('winrate')
                w3cstats.race = self.getRaceEnum(gmode_stats.get('race'))
                w3cstats.league = gmode_stats.get('leagueOrder')
                stats.append(w3cstats)
        return stats

    def getRaceEnum(self, race_int):
        if race_int is None:
            return None
        race_mapping = {
            0: Race.RANDOM,
            8: Race.UD,
            1: Race.HU,
            4: Race.NE,
            2: Race.OC
            }
        race = race_mapping.get(race_int)
        return race

    def send_request(self, method, url, data=None, headers=None, params=None):
        try:
            # Send the request
            response = requests.request(method, url, json=data, headers=headers, params=params)

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
                raise Exception(f"Request failed with status code {response.status_code}: {response.text}")

        except requests.exceptions.RequestException as e:
            # Handle network-related errors
            raise Exception(f"An exception occurred: {str(e)}")