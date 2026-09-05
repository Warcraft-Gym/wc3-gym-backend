"""The review season copies the latest season and seats the two named accounts as captains."""

from collections.abc import Callable
from typing import Any

from sqlmodel import col, select

from app.core.db import Session
from app.models.admin_grant import AdminGrant
from app.models.base import ident
from app.models.enums import Race
from app.models.match import Match
from app.models.season import Season
from app.models.series import Series
from app.models.series_replay import DBSeriesReplay
from app.models.settings import Settings
from app.models.w3c_stats import W3CStats
from app.services import replays
from app.services.review_season import NAME, WEEKS, build


def test_build_copies_the_latest_season_and_seats_the_captains(
    seeded: dict[str, Any],
    blob_store: dict[str, bytes],
    replay_uploaded: Callable[..., None],
) -> None:
    with Session.begin() as session:
        for user_id in seeded["player_ids"]:
            session.add(
                W3CStats(user_id=user_id, wc3_season=20, race=Race.HU, mmr=1500)
            )

    # an account that never signed up, and three rostered players: one pair, one left over
    build("1", "9999")
    with Session() as session:
        first = session.scalars(
            select(Series)
            .join(Match)
            .where(col(Match.season_id) != seeded["season_id"])
        ).first()
        assert first
        replay_uploaded(ident(first), 1)
        replays.confirm(ident(first), [1], None)
    assert len(blob_store) == 1

    # a second build replaces the season: its series, their replay rows and the blob go with it
    summary = build("1", "9999")

    assert "captains team" in summary
    assert blob_store == {}
    with Session() as session:
        seasons = session.scalars(select(Season).where(col(Season.name) == NAME)).all()
        assert len(seasons) == 1
        sid = seasons[0].id
        assert session.scalars(select(DBSeriesReplay)).all() == []
        current = Settings.get_by_key(session, "current_gnl_season")
        assert current and current.value == str(sid)
        matches = session.scalars(
            select(Match).where(col(Match.season_id) == sid)
        ).all()
        assert len(matches) == WEEKS
        series = session.scalars(
            select(Series).where(col(Series.match_id).in_([m.id for m in matches]))
        ).all()
        # two per week: the named accounts, then the one pair of rostered players
        assert len(series) == 2 * WEEKS
        assert session.get(AdminGrant, "1") and session.get(AdminGrant, "9999")
