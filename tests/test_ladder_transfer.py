"""export and push move ladder rows between databases keyed on battle tag."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import delete, select, update
from sqlmodel import col

from app.core.db import Session
from app.core.ladder_transfer import export, push
from app.models.enums import Race
from app.models.ladder_sync import LadderSync
from app.models.user import User
from app.models.w3c_ladder_match import W3CLadderMatch

MATCHES = "w3c_ladder_matches.csv"
SYNC = "ladder_sync.csv"


def add_rows(user_ids: list[int]) -> None:
    """Two matches and one ledger row per player; one match has empty fields."""
    when = datetime(2026, 9, 1, 12, tzinfo=UTC)
    with Session.begin() as session:
        for user_id in user_ids:
            session.add_all(
                [
                    W3CLadderMatch(
                        user_id=user_id,
                        w3c_match_id=f"m{user_id}a",
                        wc3_season=25,
                        start_time=when,
                        duration_s=600,
                        map_name="Concealed Hill",
                        race=Race.RANDOM,
                        played_race=Race.HU,
                        opp_battletag="X#1",
                        opp_race=Race.OC,
                        opp_played_race=Race.OC,
                        won=True,
                        mmr_before=1500,
                        mmr_after=1510,
                    ),
                    W3CLadderMatch(
                        user_id=user_id,
                        w3c_match_id=f"m{user_id}b",
                        wc3_season=25,
                        start_time=when,
                        duration_s=300,
                        won=False,
                    ),
                    LadderSync(
                        user_id=user_id, wc3_season=25, synced_at=when, complete=True
                    ),
                ]
            )


def snapshot() -> list[tuple[str, str]]:
    """Every ladder row as the tag and its fields, without the row id."""
    with Session() as session:
        matches = session.execute(
            select(col(User.battleTag), W3CLadderMatch).join(
                User, col(User.id) == W3CLadderMatch.user_id
            )
        ).all()
        syncs = session.execute(
            select(col(User.battleTag), LadderSync).join(
                User, col(User.id) == LadderSync.user_id
            )
        ).all()
        return sorted(
            (tag, repr(row.model_dump(exclude={"id"})))
            for tag, row in [*matches, *syncs]
        )


def clear() -> None:
    with Session.begin() as session:
        session.execute(delete(W3CLadderMatch))
        session.execute(delete(LadderSync))


def test_rows_come_back_identical_and_a_second_push_adds_none(
    seeded: dict[str, Any], tmp_path: Path
) -> None:
    add_rows(seeded["player_ids"])
    before = snapshot()

    with Session.begin() as session:
        assert export(session, tmp_path, [seeded["season_id"]]) == {
            MATCHES: 8,
            SYNC: 4,
        }
    clear()

    with Session.begin() as session:
        assert push(session, tmp_path) == {MATCHES: (8, 8, 0, 0), SYNC: (4, 4, 0, 0)}
    assert snapshot() == before

    with Session.begin() as session:
        assert push(session, tmp_path) == {MATCHES: (8, 0, 0, 0), SYNC: (4, 0, 0, 0)}


def test_an_event_filter_leaves_out_unrostered_players(
    seeded: dict[str, Any], tmp_path: Path
) -> None:
    add_rows(seeded["player_ids"])

    with Session.begin() as session:
        assert export(session, tmp_path, [seeded["season_id"] + 999]) == {
            MATCHES: 0,
            SYNC: 0,
        }


def test_an_unknown_tag_is_skipped_and_counted(
    seeded: dict[str, Any], tmp_path: Path
) -> None:
    add_rows(seeded["player_ids"][:2])
    with Session.begin() as session:
        export(session, tmp_path, [])
    clear()
    # The target knows the second player under another tag
    with Session.begin() as session:
        session.execute(
            update(User)
            .where(col(User.id) == seeded["player_ids"][1])
            .values(battleTag="Other#0")
        )

    with Session.begin() as session:
        assert push(session, tmp_path) == {MATCHES: (4, 2, 0, 2), SYNC: (2, 1, 0, 1)}


def test_an_older_ledger_row_on_the_target_takes_the_exported_values(
    seeded: dict[str, Any], tmp_path: Path
) -> None:
    add_rows(seeded["player_ids"][:1])
    with Session.begin() as session:
        export(session, tmp_path, [])
        exported = session.scalars(select(LadderSync)).one().model_dump(exclude={"id"})
        # The target read the season earlier and did not reach its end
        session.execute(
            update(LadderSync).values(
                synced_at=datetime(2026, 8, 1, tzinfo=UTC), complete=False
            )
        )

    with Session.begin() as session:
        assert push(session, tmp_path)[SYNC] == (1, 0, 1, 0)
    with Session() as session:
        row = session.scalars(select(LadderSync)).one()
        assert row.model_dump(exclude={"id"}) == exported


def test_push_refuses_a_directory_without_both_files(tmp_path: Path) -> None:
    (tmp_path / MATCHES).write_text("battle_tag\n")
    with Session.begin() as session, pytest.raises(FileNotFoundError, match=SYNC):
        push(session, tmp_path)
