"""Import a checked offline capture into an empty or previously imported local archive."""

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import make_url, select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core.db import Session, init_engine
from app.models.base import ident
from app.models.enums import EventKind, StageFormat
from app.models.event_award import EventAward
from app.models.event_division import EventDivision
from app.models.event_entrant import EventEntrant
from app.models.event_history import (
    EventVideo,
    HistoricalParticipant,
    KothHistoryEvent,
    KothHistorySeries,
)
from app.models.event_stage import EventStage
from app.models.relationships import DBEventRound
from app.models.season import Season
from app.models.series import Series
from app.models.series_game import DBSeriesGame
from app.models.types import utcnow
from app.services.koth.night import _league

# The archive board is bounded by these import limits, independent of source size.
MAX_SERIES = 500
MAX_DIVISIONS = 20
MAX_VIDEOS = 100


def digest(record: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(record, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def bounds(label: str) -> tuple[int | None, int | None]:
    """Only explicitly written numeric bounds; rank labels stay unresolved."""
    numbers = [int(value) for value in re.findall(r"\d{3,4}", label)]
    if len(numbers) == 2:
        return numbers[0], numbers[1]
    if len(numbers) == 1:
        if "below" in label.lower() or "platinum" in label.lower():
            return None, numbers[0]
        return numbers[0], None
    return None, None


def load_capture(directory: Path) -> list[dict[str, Any]]:
    """Verify every file in the capture manifest before reading its event records."""
    directory = directory.resolve()
    checked = set()
    for line in (directory / "SHA256SUMS").read_text().splitlines():
        expected, name = line.split(maxsplit=1)
        path = (directory / name.lstrip(" *")).resolve()
        if not path.is_relative_to(directory):
            raise ValueError("Capture checksum path leaves its directory")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Capture checksum mismatch: {path.name}")
        checked.add(path.name)
    if not {"events.json", "manifest.json"} <= checked:
        raise ValueError("Capture manifest must cover events.json and manifest.json")
    records = json.loads((directory / "events.json").read_text())
    validate(records)
    return records


def validate(records: list[dict[str, Any]]) -> Counter[str]:
    """Validate the whole batch before its first write and account for every source row."""
    counts: Counter[str] = Counter()
    keys: set[str] = set()
    for event in records:
        key = event["event_id"]
        if not key or key in keys or len(key) > 200:
            raise ValueError("Missing, duplicate or oversized source event key")
        keys.add(key)
        if event["date"]:
            date.fromisoformat(event["date"])
        else:
            counts["unresolved_dates"] += 1
        counts["events"] += 1
        nseries = ndivisions = 0
        for section in event["sections"]:
            bracket = section["kind"] == "bracket"
            if bracket:
                ndivisions += 1
                if not section["title"] or len(section["title"]) > 50:
                    raise ValueError("Bracket label is missing or too long")
            for row in section["matches"]:
                counts["source_rows"] += 1
                if not bracket or row["record_type"] != "match":
                    counts["excluded_rows"] += 1
                    continue
                for name in (row["player_1"], row["player_2"]):
                    if not isinstance(name, str) or not name.strip() or len(name) > 200:
                        raise ValueError(f"Unresolved side in {key}: {row['raw_text']}")
                if row["winner"] is not None and row["winner"] not in (
                    row["player_1"],
                    row["player_2"],
                ):
                    raise ValueError("Explicit winner does not name a side")
                counts["known_results" if row["winner"] else "unknown_results"] += 1
                nseries += 1
            if bracket:
                counts["crowns"] += len(section["crowns"])
                for crown in section["crowns"]:
                    if not crown["player"] or len(crown["player"]) > 200:
                        raise ValueError("Crown participant is missing or too long")
        videos = event["videos"]
        if len({v["video_id"] for v in videos}) != len(videos):
            raise ValueError("Duplicate video in event")
        for video in videos:
            if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video["video_id"]):
                raise ValueError("Invalid YouTube video key")
        if (
            nseries > MAX_SERIES
            or ndivisions > MAX_DIVISIONS
            or len(videos) > MAX_VIDEOS
        ):
            raise ValueError("Event exceeds the archive board read limits")
        counts.update(
            series=nseries, games=nseries, divisions=ndivisions, videos=len(videos)
        )
    return counts


def import_capture(
    records: list[dict[str, Any]], *, apply: bool = False
) -> dict[str, Any]:
    """Dry-run by default; each new event commits atomically, and reruns never overwrite."""
    counts = validate(records)
    with Session() as session:
        existing = {
            row.source_key: row for row in session.scalars(select(KothHistoryEvent))
        }
        # Existing KOTH events need an explicit reconciliation before this empty-target importer runs.
        unowned = session.scalar(
            select(col(Season.id))
            .where(
                col(Season.kind) == EventKind.koth,
                ~col(Season.id).in_(select(col(KothHistoryEvent.event_id))),
            )
            .limit(1)
        )
        if unowned is not None:
            raise ValueError(
                "Target has KOTH events without source mappings; reconcile them before importing"
            )
        for record in records:
            old = existing.get(record["event_id"])
            if old is not None and old.source_digest != digest(record):
                raise ValueError(
                    f"Source drift: {record['event_id']}; no records changed"
                )
    mapping = {key: row.event_id for key, row in existing.items()}
    inserted = 0
    if apply:
        for record in sorted(
            records, key=lambda row: (row["date"] or "", row["event_id"])
        ):
            if record["event_id"] in mapping:
                continue
            with Session.begin() as session:
                event_id = _insert_event(session, record)
            mapping[record["event_id"]] = event_id
            inserted += 1
    return {
        "mode": "apply" if apply else "dry_run",
        "counts": dict(counts),
        "inserted_events": inserted,
        "existing_events": sum(record["event_id"] in existing for record in records),
        "event_ids": mapping,
    }


def _insert_event(session: OrmSession, record: dict[str, Any]) -> int:
    day = date.fromisoformat(record["date"]) if record["date"] else None
    name = f"KOTH {record['date_text']}"
    duplicate = 1
    while (
        session.scalar(select(col(Season.id)).where(col(Season.name) == name))
        is not None
    ):
        duplicate += 1
        name = f"KOTH {record['date_text']} ({duplicate})"
    event = Season(
        name=name,
        series_per_round=1,
        league_id=_league(session),
        kind=EventKind.koth,
        start_date=day,
        end_date=day,
        signups_open=False,
        scheduling_enabled=False,
        checkin_enabled=False,
        published=True,
        closed_at=utcnow(),
        page_url=record["source_url"],
    )
    session.add(event)
    session.flush()
    event_id = ident(event)
    session.add(
        KothHistoryEvent(
            event_id=event_id,
            source_key=record["event_id"],
            source_url=record["source_url"],
            source_digest=digest(record),
            date_label=record["date_text"],
            source_record=record,
        )
    )
    stage = EventStage(event_id=event_id, format=StageFormat.koth, best_of=1)
    session.add(stage)
    session.flush()
    round_ = DBEventRound(
        season_id=event_id,
        stage_id=ident(stage),
        number=1,
        start_date=day,
        end_date=day,
    )
    session.add(round_)
    session.flush()
    for section_no, section in enumerate(record["sections"], 1):
        if section["kind"] != "bracket":
            continue
        division = EventDivision(
            event_id=event_id,
            position=section_no,
            name=section["title"],
            lower_bound=bounds(section["title"])[0],
        )
        session.add(division)
        session.flush()
        entrants: dict[str, EventEntrant] = {}

        def participant(
            name: str,
            entrants: dict[str, EventEntrant] = entrants,
            section_no: int = section_no,
            division: EventDivision = division,
        ) -> EventEntrant:
            if name not in entrants:
                person = HistoricalParticipant(
                    event_id=event_id,
                    source_key=f"{section_no}:{len(entrants) + 1}",
                    source_name=name,
                )
                session.add(person)
                session.flush()
                entrant = EventEntrant(
                    event_id=event_id,
                    division_id=ident(division),
                    historical_participant_id=ident(person),
                )
                session.add(entrant)
                session.flush()
                entrants[name] = entrant
            return entrants[name]

        for ordinal, row in enumerate(section["matches"], 1):
            if row["record_type"] != "match":
                continue
            first, second = participant(row["player_1"]), participant(row["player_2"])
            winner = (
                "A"
                if row["winner"] == row["player_1"]
                else "B"
                if row["winner"] == row["player_2"]
                else None
            )
            series = Series(
                round_id=ident(round_),
                division_id=ident(division),
                sequence=ordinal,
                entrant1_id=ident(first),
                entrant2_id=ident(second),
                host_player_id=0,
                result_unavailable=winner is None,
                player1_score=int(winner == "A") if winner else None,
                player2_score=int(winner == "B") if winner else None,
            )
            session.add(series)
            session.flush()
            session.add(
                DBSeriesGame(series_id=ident(series), game_no=1, winner_side=winner)
            )
            session.add(
                KothHistorySeries(
                    series_id=ident(series),
                    event_id=event_id,
                    source_key=f"{section_no}:{ordinal}",
                    source_record=row,
                )
            )
        for crown in section["crowns"]:
            king = participant(crown["player"])
            division.king_entrant_id = ident(king)
            session.add(
                EventAward(
                    event_id=event_id,
                    entrant_id=ident(king),
                    title="Champion",
                    place=1,
                    awarded_at=None,
                )
            )
    for ordinal, video in enumerate(record["videos"], 1):
        session.add(
            EventVideo(
                event_id=event_id,
                provider="youtube",
                video_key=video["video_id"],
                url=f"https://www.youtube.com/watch?v={video['video_id']}",
                title=video.get("title"),
                position=ordinal,
            )
        )
    return event_id


def local_url(value: str) -> str:
    """The import command accepts only an explicit loopback Postgres URL, without overrides."""
    url = make_url(value)
    if (
        url.drivername != "postgresql+psycopg"
        or url.host not in {"localhost", "127.0.0.1", "::1"}
        or url.query
    ):
        raise ValueError(
            "Use an explicit loopback PostgreSQL URL without query parameters"
        )
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--database-url", required=True, type=local_url)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    records = load_capture(args.capture)
    init_engine(args.database_url)
    print(json.dumps(import_capture(records, apply=args.apply), indent=2))


if __name__ == "__main__":
    main()
