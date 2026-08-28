"""Save one page of a player's w3champions matches as a test fixture.

Run: uv run tests/data/w3c/capture.py "thanks#11187" 25 [page_size] [offset]
"""

import json
import re
import sys
from pathlib import Path

import requests

URL = "https://website-backend.w3champions.com/api/matches/search"


def capture(battle_tag: str, season: int, page_size: int, offset: int) -> Path:
    body = requests.get(
        URL,
        params={
            "playerId": battle_tag,
            "gateway": 20,
            "gameMode": 1,
            "season": season,
            "pageSize": page_size,
            "offset": offset,
        },
        timeout=30,
    ).json()
    name = re.sub(r"\W+", "_", battle_tag.lower())
    path = Path(__file__).parent / f"{name}_season{season}.json"
    path.write_text(json.dumps(body))
    return path


if __name__ == "__main__":
    tag, season = sys.argv[1], int(sys.argv[2])
    size = int(sys.argv[3]) if len(sys.argv) > 3 else 100
    start = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    print(capture(tag, season, size, start))
