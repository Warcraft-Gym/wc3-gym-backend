"""The GNL payloads, pinned byte for byte while the events tables are built.

The events module renames `seasons` to `event` over four deploys. Nothing a
GNL page reads may change while that happens, so this test snapshots the
reads the season pages, the dashboard and the Discord card are built from
and compares them to tests/data/gnl_snapshot.json. A later migration that
shifts a field fails here before it reaches a page.

Set UPDATE_GNL_SNAPSHOT=1 to write the file again, and read the diff: a
change to it is a change to a public contract.
"""

import json
import os
from pathlib import Path
from typing import Any

import pytest
from httpx2 import Client

from tests.test_player_session import member_session

SNAPSHOT = Path(__file__).parent / "data" / "gnl_snapshot.json"


@pytest.fixture
def pinned_season(seeded: dict[str, Any]) -> dict[str, Any]:
    """The seeded league with its season pinned as the current one."""
    from app.core.db import Session
    from app.models.settings import Settings

    with Session.begin() as session:
        session.add(Settings(key="current_gnl_season", value=str(seeded["season_id"])))
    return seeded


def gnl_payloads(
    client: Client, seeded: dict[str, Any], headers: dict[str, str]
) -> dict[str, Any]:
    """Every GNL read the snapshot covers, keyed by the call that answers it."""
    from app.models.series import SeriesPublic
    from app.services import series_cards

    season_id = seeded["season_id"]
    player_id = seeded["player_ids"][0]

    def get(path: str, **kwargs: Any) -> Any:  # noqa: ANN401
        resp = client.get(path, **kwargs)
        assert resp.status_code == 200, resp.text
        return resp.json()

    matches = client.post(f"/matches/search?query=season_id == {season_id}")
    assert matches.status_code == 200, matches.text
    series = get(f"/series/season/{season_id}")
    # The /upcoming reply, whose card text hangs on the round and the match
    cards = series_cards.upcoming(
        [SeriesPublic.model_validate(row) for row in series], lambda _: False
    )
    return {
        "GET /seasons": get("/seasons"),
        f"GET /seasons/{season_id}": get(f"/seasons/{season_id}"),
        f"GET /series/season/{season_id}": series,
        "POST /matches/search?query=season_id": matches.json(),
        f"GET /users/{player_id}": get(f"/users/{player_id}"),
        f"GET /users/{player_id}/history": get(f"/users/{player_id}/history"),
        "GET /player-series": get("/player-series", headers=headers),
        "/upcoming": cards,
    }


def test_the_gnl_payloads_are_unchanged(
    client: Client, pinned_season: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    payloads = gnl_payloads(client, pinned_season, member_session(monkeypatch))

    if os.getenv("UPDATE_GNL_SNAPSHOT"):
        SNAPSHOT.write_text(json.dumps(payloads, indent=2, sort_keys=True) + "\n")

    assert payloads == json.loads(SNAPSHOT.read_text())
