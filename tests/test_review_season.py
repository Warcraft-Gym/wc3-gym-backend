"""The review season copies the latest season, seats the test guild and rotates the pairings."""

from collections.abc import Callable
from typing import Any

import pytest
from sqlmodel import col, select

from app.core.achievements import DEFAULT_PAID
from app.core.db import Session
from app.models.admin_grant import AdminGrant
from app.models.base import ident
from app.models.enums import Race
from app.models.fantasy_team import FantasyTeam
from app.models.ladder_achievement import LadderAchievement
from app.models.match import Match
from app.models.relationships import DBFantasyTeamPlayer, DBSeasonRound
from app.models.season import Season
from app.models.series import Series
from app.models.series_replay import DBSeriesReplay
from app.models.settings import Settings
from app.models.user import User
from app.models.w3c_stats import W3CStats
from app.services import replays, review_season
from app.services.review_season import NAME, ROUND_WEEKS, ROUNDS, START, build

# the two named accounts and one more human; the bot in the guild never plays
GUILD = ["1", "9999", "5555"]


@pytest.fixture(autouse=True)
def guild(monkeypatch: pytest.MonkeyPatch) -> None:
    """The test guild the seed reads, so no test reaches Discord."""
    members: list[dict[str, Any]] = [
        {"user": {"id": discord_id}} for discord_id in GUILD
    ]
    members.append({"user": {"id": "7000", "bot": True}})
    monkeypatch.setattr(review_season.discord, "guild_member_list", lambda: members)


def with_ladder_mmr(player_ids: list[int]) -> None:
    """Give the seeded players an MMR, which the roster query asks for."""
    with Session.begin() as session:
        for user_id in player_ids:
            session.add(
                W3CStats(user_id=user_id, wc3_season=20, race=Race.HU, mmr=1500)
            )


def test_build_copies_the_latest_season_and_seats_the_captains(
    seeded: dict[str, Any],
    blob_store: dict[str, bytes],
    replay_uploaded: Callable[..., None],
) -> None:
    with_ladder_mmr(seeded["player_ids"])

    # an account that never signed up, a third guild account and three rostered players
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
        season = seasons[0]
        sid = season.id
        assert season.start_date == START
        assert season.number_rounds == ROUNDS
        assert session.scalars(select(DBSeriesReplay)).all() == []
        current = Settings.get_by_key(session, "current_gnl_season")
        assert current and current.value == str(sid)

        # the season pays the same badges a season created in the app pays
        paid = session.scalars(
            select(col(LadderAchievement.rule_id)).where(
                col(LadderAchievement.season_id) == sid
            )
        ).all()
        assert set(paid) == set(DEFAULT_PAID)

        rounds = session.scalars(
            select(DBSeasonRound)
            .where(col(DBSeasonRound.season_id) == sid)
            .order_by(col(DBSeasonRound.playday))
        ).all()
        assert len(rounds) == ROUNDS
        assert rounds[0].start_date == START
        assert (rounds[1].start_date - rounds[0].start_date).days == 7 * ROUND_WEEKS
        assert (rounds[0].end_date - rounds[0].start_date).days == 7 * ROUND_WEEKS - 1

        matches = session.scalars(
            select(Match).where(col(Match.season_id) == sid)
        ).all()
        assert len(matches) == ROUNDS
        series = session.scalars(
            select(Series).where(col(Series.match_id).in_([m.id for m in matches]))
        ).all()
        # three guild accounts and three rostered players make three series a round
        assert len(series) == 3 * ROUNDS
        assert session.get(AdminGrant, "1") and session.get(AdminGrant, "9999")


def test_a_rebuild_clears_a_fantasy_team_of_the_old_season(
    seeded: dict[str, Any],
) -> None:
    with_ladder_mmr(seeded["player_ids"])
    build("1", "9999")

    # fantasy_team_player has no cascade from fantasy_teams, so a drafted player
    # used to block the season delete
    with Session.begin() as session:
        season = session.scalar(select(Season).where(col(Season.name) == NAME))
        assert season
        team = FantasyTeam(
            season_id=ident(season),
            name="test team",
            captain_id=seeded["player_ids"][0],
        )
        session.add(team)
        session.flush()
        team_id = ident(team)
        session.add(
            DBFantasyTeamPlayer(
                fantasy_team_id=team_id, user_id=seeded["player_ids"][1]
            )
        )

    build("1", "9999")

    with Session() as session:
        assert session.get(FantasyTeam, team_id) is None
        assert (
            session.scalars(
                select(DBFantasyTeamPlayer).where(
                    col(DBFantasyTeamPlayer.fantasy_team_id) == team_id
                )
            ).all()
            == []
        )


def test_pairings_rotate_and_guild_series_stay_unscheduled(
    seeded: dict[str, Any],
) -> None:
    with_ladder_mmr(seeded["player_ids"])
    build("1", "9999")

    with Session() as session:
        sid = session.scalar(select(col(Season.id)).where(col(Season.name) == NAME))
        matches = session.scalars(
            select(Match).where(col(Match.season_id) == sid)
        ).all()
        series = session.scalars(
            select(Series).where(col(Series.match_id).in_([m.id for m in matches]))
        ).all()
        guild_users = {
            user.id
            for user in session.scalars(
                select(User).where(col(User.discordId).in_(GUILD))
            )
        }
    assert len(guild_users) == len(GUILD)

    # nobody meets the same opponent twice
    pairs = {(row.player1_id, row.player2_id) for row in series}
    assert len(pairs) == len(series)

    unscheduled = [row for row in series if row.date_time is None]
    scheduled = [row for row in series if row.date_time is not None]
    assert unscheduled and scheduled
    for row in unscheduled:
        assert {row.player1_id, row.player2_id} & guild_users
    for row in scheduled:
        assert not {row.player1_id, row.player2_id} & guild_users
        assert row.date_time and row.date_time.hour == 20
