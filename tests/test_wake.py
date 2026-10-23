"""A commit that can move the next reminder card or cup call tells the Worker.

The Worker holds the last `next_run` pushed and calls /jobs/cast-reminders
only then, so each write path below must leave it holding what
wake.next_run reads after the write. The clock stands still at `now`, so the
value pushed and the value read are the same reading of the same rows.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import Enum
from itertools import count
from types import SimpleNamespace
from typing import Any

import pytest
import requests
from httpx2 import Client
from sqlalchemy import delete, update
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import class_mapper
from sqlalchemy.orm.attributes import flag_modified
from sqlmodel import col, select
from sqlmodel.main import default_registry

from app.api.routes import jobs
from app.core.db import Session
from app.models.base import ident
from app.models.discord_post import DiscordPost
from app.models.relationships import DBEventRound
from app.models.series import Series
from app.models.series_cast import SeriesCast
from app.models.settings import Settings
from app.services import casts, discord_posts, wake
from tests.test_awards import play_out
from tests.test_cup_divisions import field_of, make_cup
from tests.test_cup_rounds import finish_leg, legs_of
from tests.test_discord_auth import SESSION
from tests.test_discord_cast_post import CONTENT, as_member, claim
from tests.test_event_organizers import CUP, Headers
from tests.test_koth import EVENT
from tests.test_stage_engine import generate

WORKER = "https://worker.test"
JOB = "/jobs/cast-reminders"
SECRET = {"Authorization": "Bearer cast-secret"}
HOUR = timedelta(hours=1)

type Worker = dict[str, Any]


@pytest.fixture
def now(monkeypatch: pytest.MonkeyPatch) -> datetime:
    """The moment every push reads the rows at."""
    moment = datetime.now(UTC).replace(microsecond=0)
    monkeypatch.setattr(wake, "utcnow", lambda: moment)
    return moment


@pytest.fixture
def worker(monkeypatch: pytest.MonkeyPatch, now: datetime) -> Worker:
    """The Worker's state, the last `next_run` pushed, and every push it took."""
    held: Worker = {"next_run": None, "calls": []}

    def take(url: str, **kwargs: Any) -> SimpleNamespace:  # noqa: ANN401
        held["calls"].append((url, kwargs))
        held["next_run"] = kwargs["json"]["next_run"]
        return SimpleNamespace(status_code=204, raise_for_status=lambda: None)

    monkeypatch.setattr(wake, "post", take)
    monkeypatch.setenv("CLOUDFLARE_WORKER_URL", WORKER)
    monkeypatch.setenv("CLOUDFLARE_CRON_SECRET", "cast-secret")
    return held


@pytest.fixture
def cron(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLOUDFLARE_CRON_SECRET", "cast-secret")


def pushes(worker: Worker) -> int:
    return len(worker["calls"])


def holds(worker: Worker, now: datetime) -> str:
    """Assert the Worker holds what wake.next_run reads now, and answer it."""
    expected = wake.next_run(now).isoformat()
    assert worker["next_run"] == expected
    return expected


def starts_at(series_id: int, at: datetime) -> None:
    with Session.begin() as session:
        session.get_one(Series, series_id).date_time = at


def test_a_push_posts_the_next_run_with_the_bearer(
    worker: Worker, now: datetime
) -> None:
    wake.push()
    [(url, kwargs)] = worker["calls"]
    assert url == f"{WORKER}/next-run"
    assert kwargs == {
        "json": {"next_run": (now + wake.FLOOR).isoformat()},
        "headers": {"Authorization": "Bearer cast-secret"},
        "timeout": 2,
    }


# ============ Every watched table, written through the ORM ============
serial = count(1)


def _mapped(table: Any) -> type:  # noqa: ANN401
    return next(m.class_ for m in default_registry.mappers if m.local_table is table)


def _sample(column: Any, now: datetime) -> Any:  # noqa: ANN401
    # a TypeDecorator such as AutoString names its type on the type it wraps
    kind = getattr(column.type, "impl", column.type).python_type
    if issubclass(kind, Enum):
        return next(iter(kind))
    if kind is datetime:
        return now
    if kind is bool:
        return False
    return next(serial) if kind is int else f"w{next(serial)}"


def build(session: OrmSession, model: type, now: datetime) -> Any:  # noqa: ANN401
    """A row of `model` with each required column filled, a parent row first
    for each required foreign key."""
    values: dict[str, Any] = {}
    for column in class_mapper(model).local_table.columns:
        if column.primary_key or column.nullable or column.default is not None:
            continue
        if column.server_default is not None:
            continue
        if column.foreign_keys:
            target = next(iter(column.foreign_keys)).column
            parent = build(session, _mapped(target.table), now)
            values[column.key] = getattr(parent, target.key)
        else:
            values[column.key] = _sample(column, now)
    row = model(**values)
    session.add(row)
    session.flush()
    return row


@pytest.mark.parametrize("model", wake.WATCHED, ids=lambda model: model.__name__)
def test_an_insert_an_update_and_a_delete_each_push(
    model: type, worker: Worker, now: datetime
) -> None:
    with Session.begin() as session:
        row = build(session, model, now)
        key = row.id
    assert pushes(worker) == 1
    holds(worker, now)

    with Session.begin() as session:
        row = session.get_one(model, key)
        # an UPDATE of a column the row has, to the value it holds
        attr = next(
            a for a in class_mapper(model).column_attrs if not a.columns[0].primary_key
        )
        flag_modified(row, attr.key)
    assert pushes(worker) == 2
    holds(worker, now)

    with Session.begin() as session:
        session.delete(session.get_one(model, key))
    assert pushes(worker) == 3
    holds(worker, now)


def test_a_bulk_delete_of_series_pushes_and_another_table_does_not(
    seeded: dict[str, Any], worker: Worker, now: datetime
) -> None:
    before = pushes(worker)
    with Session.begin() as session:
        session.execute(
            delete(Series).where(col(Series.id) == seeded["series_open_id"])
        )
    assert pushes(worker) == before + 1
    holds(worker, now)

    with Session.begin() as session:
        session.add(Settings(key="unwatched", value="1"))
        session.execute(update(Settings).values(value="2"))
        session.execute(delete(Settings).where(col(Settings.key) == "unwatched"))
    assert pushes(worker) == before + 1


def test_a_rolled_back_write_pushes_nothing(
    seeded: dict[str, Any], worker: Worker, now: datetime
) -> None:
    before = pushes(worker)
    with Session() as session:
        session.get_one(Series, seeded["series_open_id"]).date_time = now
        session.flush()
        session.rollback()
        # the same session's next commit writes no watched table, so it pushes nothing
        session.add(Settings(key="unwatched", value="1"))
        session.commit()
    assert pushes(worker) == before


def test_a_savepoint_defers_the_push_to_the_outer_commit(
    seeded: dict[str, Any], worker: Worker, now: datetime
) -> None:
    before = pushes(worker)
    with Session.begin() as session:
        session.get_one(Series, seeded["series_open_id"]).date_time = now + HOUR
        with session.begin_nested():
            session.add(Settings(key="unwatched", value="1"))
        assert pushes(worker) == before
        with pytest.raises(RuntimeError), session.begin_nested():
            session.add(Settings(key="rolled-back", value="1"))
            session.flush()
            raise RuntimeError
    assert pushes(worker) == before + 1
    holds(worker, now)


# ============ Each write path reachable today ============
def claimed(
    client: Client,
    monkeypatch: pytest.MonkeyPatch,
    seeded: dict[str, Any],
    at: datetime,
) -> int:
    """The open seeded series, starting at `at`, claimed by player 1."""
    series_id = seeded["series_open_id"]
    starts_at(series_id, at)
    as_member(monkeypatch, "1")
    claim(client, series_id)
    return series_id


def test_cast_claim_pushes(
    client: Client,
    seeded: dict[str, Any],
    worker: Worker,
    now: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    starts_at(seeded["series_open_id"], now + 3 * HOUR)
    assert holds(worker, now) == (now + wake.FLOOR).isoformat()
    claimed(client, monkeypatch, seeded, now + 3 * HOUR)
    assert holds(worker, now) == (now + 3 * HOUR - casts.REMINDER_LEAD).isoformat()


def test_cast_update_pushes(
    client: Client,
    seeded: dict[str, Any],
    worker: Worker,
    now: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    series_id = claimed(client, monkeypatch, seeded, now + 3 * HOUR)
    cast_id = client.get(f"/series/{series_id}/casts").json()[0]["id"]
    before = pushes(worker)
    resp = client.put(
        f"/series/{series_id}/casts/{cast_id}",
        json={"channel_url": "twitch.tv/another"},
        headers=SESSION,
    )
    assert resp.status_code == 200, resp.text
    assert pushes(worker) == before + 1
    holds(worker, now)


def test_cast_unclaim_pushes(
    client: Client,
    seeded: dict[str, Any],
    worker: Worker,
    now: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    series_id = claimed(client, monkeypatch, seeded, now + 3 * HOUR)
    cast_id = client.get(f"/series/{series_id}/casts").json()[0]["id"]
    resp = client.delete(f"/series/{series_id}/casts/{cast_id}", headers=SESSION)
    assert resp.status_code == 204, resp.text
    assert holds(worker, now) == (now + wake.FLOOR).isoformat()


def test_series_date_change_pushes(
    client: Client,
    auth_headers: Headers,
    seeded: dict[str, Any],
    worker: Worker,
    now: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    series_id = claimed(client, monkeypatch, seeded, now + 3 * HOUR)
    resp = client.put(
        f"/series/{series_id}",
        json={"date_time": (now + HOUR).isoformat()},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert holds(worker, now) == (now + HOUR - casts.REMINDER_LEAD).isoformat()


def test_series_result_on_a_claimed_series_pushes(
    client: Client,
    auth_headers: Headers,
    seeded: dict[str, Any],
    worker: Worker,
    now: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    series_id = claimed(client, monkeypatch, seeded, now + 3 * HOUR)
    resp = client.put(
        f"/series/{series_id}",
        json={"player1_score": 2, "player2_score": 0},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    # a played series calls nobody, so the Worker falls back to the floor
    assert holds(worker, now) == (now + wake.FLOOR).isoformat()


def test_cup_create_pushes(
    client: Client, auth_headers: Headers, worker: Worker, now: datetime
) -> None:
    made = client.post(
        "/events",
        json=CUP
        | {"checkin_enabled": False, "starts_at": (now + 3 * HOUR).isoformat()},
        headers=auth_headers,
    )
    assert made.status_code == 201, made.text
    # a cup that takes no check-in is called an hour before it starts
    assert holds(worker, now) == (now + 2 * HOUR).isoformat()


def test_cup_leg_create_pushes(
    client: Client, auth_headers: Headers, worker: Worker, now: datetime
) -> None:
    past = [{"starts_at": (now - days * 24 * HOUR).isoformat()} for days in (2, 1)]
    cup = make_cup(client, auth_headers, legs=past)
    assert holds(worker, now) == (now + wake.FLOOR).isoformat()
    added = client.post(
        f"/events/{cup['id']}/legs",
        json={"starts_at": (now + 3 * HOUR).isoformat()},
        headers=auth_headers,
    )
    assert added.status_code == 201, added.text
    assert holds(worker, now) != (now + wake.FLOOR).isoformat()


def test_cup_leg_finish_pushes(
    client: Client, auth_headers: Headers, worker: Worker, now: datetime
) -> None:
    legs = [{"starts_at": (now + hours * HOUR).isoformat()} for hours in (3, 30)]
    cup = make_cup(client, auth_headers, legs=legs)
    field_of(cup["id"], (2000, 1900, 1800, 1700))
    first = legs_of(client, cup["id"])[0]
    everyone = client.post(
        f"/events/{cup['id']}/legs/{first['id']}/checkins/everyone",
        headers=auth_headers,
    )
    assert everyone.status_code == 200, everyone.text
    stage = first["stage_ids"][0]
    generate(client, auth_headers, cup["id"], stage)
    play_out(client, auth_headers, stage)
    assert holds(worker, now) != (now + wake.FLOOR).isoformat()

    done = finish_leg(client, auth_headers, cup["id"], first["id"])
    assert done.status_code == 200, done.text
    # the second round is called past the floor
    assert holds(worker, now) == (now + wake.FLOOR).isoformat()


def test_koth_legacy_delete_pushes(
    client: Client, auth_headers: Headers, worker: Worker, now: datetime
) -> None:
    night = client.post("/koth/events", headers=auth_headers, json=EVENT)
    assert night.status_code == 201, night.text
    event_id = night.json()["id"]
    # a claimed series in the night's round, three hours ahead
    with Session.begin() as session:
        night_round = DBEventRound(season_id=event_id, number=1)
        session.add(night_round)
        session.flush()
        series = Series(
            round_id=night_round.id, date_time=now + 3 * HOUR, host_player_id=0
        )
        session.add(series)
        session.flush()
        session.add(SeriesCast(series_id=ident(series), channel_url="twitch.tv/x"))
    assert holds(worker, now) == (now + 3 * HOUR - casts.REMINDER_LEAD).isoformat()

    resp = client.delete(f"/koth/events/{event_id}", headers=auth_headers)
    assert resp.status_code == 204, resp.text
    assert holds(worker, now) == (now + wake.FLOOR).isoformat()


# ============ A push that fails ============
def test_no_worker_url_pushes_nothing(
    seeded: dict[str, Any], worker: Worker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CLOUDFLARE_WORKER_URL")
    before = pushes(worker)
    starts_at(seeded["series_open_id"], datetime.now(UTC))
    assert pushes(worker) == before


def _refused() -> SimpleNamespace:
    def raise_for_status() -> None:
        raise requests.HTTPError(response=SimpleNamespace(status_code=401))  # type: ignore[arg-type]

    return SimpleNamespace(status_code=401, raise_for_status=raise_for_status)


def _unreachable() -> SimpleNamespace:
    raise requests.ConnectionError


@pytest.mark.parametrize(
    "answer", [_refused, _unreachable], ids=["non-2xx", "connection-error"]
)
def test_a_failed_push_is_logged_and_the_write_still_answers(
    answer: Callable[[], SimpleNamespace],
    client: Client,
    seeded: dict[str, Any],
    worker: Worker,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(wake, "post", lambda *args, **kwargs: answer())
    with caplog.at_level(logging.WARNING, logger=wake.__name__):
        as_member(monkeypatch, "1")
        claim(client, seeded["series_open_id"])
    assert any("next-run push failed" in r.getMessage() for r in caplog.records)
    assert client.get(f"/series/{seeded['series_open_id']}/casts").json() != []


# ============ The route ============
def test_the_route_answers_the_floor_with_nothing_due(
    client: Client, cron: None, monkeypatch: pytest.MonkeyPatch, now: datetime
) -> None:
    monkeypatch.setattr(jobs, "utcnow", lambda: now)
    body = client.get(JOB, headers=SECRET).json()
    assert body["next_run"] == (now + wake.FLOOR).isoformat()
    assert body["next_run"] == wake.next_run(now).isoformat()


@pytest.fixture
def content_channel() -> None:
    with Session.begin() as session:
        session.add(Settings(key="content_channel_id", value="content"))


def backdate_claim(series_id: int, ago: timedelta) -> None:
    """Move the series' claims to `ago` before now, as a claim made earlier."""
    with Session.begin() as session:
        for cast in session.scalars(
            select(SeriesCast).where(col(SeriesCast.series_id) == series_id)
        ):
            cast.created_at = datetime.now(UTC) - ago


@pytest.mark.parametrize(
    ("minutes", "claimed_ago", "late"),
    [
        # due 10 minutes ago, claimed 20 minutes ago: owed for 10 minutes
        (5, timedelta(minutes=20), 1),
        # due 10 minutes ago, claimed just now: owed since the claim, not late
        (5, timedelta(0), 0),
        # due now
        (15, timedelta(minutes=20), 0),
    ],
    ids=["late", "late-claim", "on-time"],
)
def test_a_card_posted_after_it_was_owed_counts_as_late(
    minutes: int,
    claimed_ago: timedelta,
    late: int,
    client: Client,
    seeded: dict[str, Any],
    discord_calls: list,
    content_channel: None,
    cron: None,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(wake, "post", lambda *args, **kwargs: None)
    series_id = seeded["series_open_id"]
    starts_at(series_id, datetime.now(UTC) + timedelta(minutes=minutes))
    as_member(monkeypatch, "1")
    claim(client, series_id)
    backdate_claim(series_id, claimed_ago)
    with caplog.at_level(logging.WARNING, logger=jobs.__name__):
        body = client.get(JOB, headers=SECRET).json()
    assert (body["posted"], body["late"]) == (1, late)
    assert [call[:2] for call in discord_calls][-1] == ("POST", CONTENT)
    warned = [r.getMessage() for r in caplog.records if "posted late" in r.getMessage()]
    assert warned == ([f"reminder cards posted late: series [{series_id}]"] * late)


def unseen_claim(
    series_id: int, started: timedelta, claimed: timedelta, carded: bool = False
) -> None:
    """The series started `started` ago, claimed `claimed` ago, and with its card
    when `carded`; written straight to the rows, as the job finds them."""
    moment = datetime.now(UTC)
    with Session.begin() as session:
        session.get_one(Series, series_id).date_time = moment - started
        session.add(
            SeriesCast(
                series_id=series_id,
                channel_url="twitch.tv/x",
                created_at=moment - claimed,
            )
        )
        if carded:
            session.add(
                DiscordPost(
                    kind=discord_posts.REMINDER,
                    subject_id=series_id,
                    channel_id="content",
                    message_id="msg-9",
                )
            )


@pytest.mark.parametrize(
    ("started", "claimed_ago", "carded", "missed"),
    [
        (2 * HOUR, 3 * HOUR, False, 1),
        # claimed after the late cutoff: it never owed a card
        (2 * HOUR, HOUR, False, 0),
        (2 * HOUR, 3 * HOUR, True, 0),
        # still inside the window starting_soon posts in
        (timedelta(minutes=10), HOUR, False, 0),
    ],
    ids=["missed", "claimed-late", "carded", "still-due"],
)
def test_a_claimed_series_that_started_without_its_card_counts_as_missed(
    started: timedelta,
    claimed_ago: timedelta,
    carded: bool,
    missed: int,
    client: Client,
    seeded: dict[str, Any],
    cron: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    series_id = seeded["series_open_id"]
    unseen_claim(series_id, started, claimed_ago, carded)
    with caplog.at_level(logging.WARNING, logger=jobs.__name__):
        body = client.get(JOB, headers=SECRET).json()
    assert body["missed"] == missed
    warned = [
        r.getMessage() for r in caplog.records if "never posted" in r.getMessage()
    ]
    assert warned == ([f"reminder cards never posted: series [{series_id}]"] * missed)
