"""Import a checked offline capture into an empty or previously imported local archive."""

import argparse
import calendar
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from datetime import date
from difflib import SequenceMatcher
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


# A parenthesis naming a race is evidence of the race, not a note about the result
RACE_TAGS = {
    "hu",
    "human",
    "orc",
    "oc",
    "ud",
    "undead",
    "ne",
    "nightelf",
    "elf",
    "rdm",
    "random",
    "offrace",
}


def _name(value: str) -> str:
    return re.sub(r"[^0-9a-z]", "", value.casefold())


def fold(name: str) -> str:
    """A written name trimmed, with inner whitespace collapsed to one space, lowercase."""
    return " ".join(name.split()).lower()


def read_corrections(
    corrections: object, records: list[dict[str, Any]]
) -> tuple[dict[str, date], dict[str, str]]:
    """The reviewed dates by source key and kept names by folded spelling, checked whole.

    A date only dates a record the page leaves undated; a key that names no
    record of the batch is ignored. A kept name is corrected to nothing but itself.
    """
    if not isinstance(corrections, dict):
        raise ValueError("The corrections file is not a JSON object")  # noqa: TRY004
    dates = corrections.get("dates", {})
    names = corrections.get("names", {})
    if (
        corrections.keys() - {"dates", "names"}
        or not isinstance(dates, dict)
        or not isinstance(names, dict)
    ):
        raise ValueError("The corrections file holds only a dates map and a names map")
    undated = {record["event_id"]: not record["date"] for record in records}
    days: dict[str, date] = {}
    for key, value in dates.items():
        if not undated.get(key, True):
            raise ValueError(
                f"The corrections file dates {key}, which has its own date"
            )
        try:
            days[key] = date.fromisoformat(value)
        except (TypeError, ValueError):
            raise ValueError(
                f"The corrections date of {key} is not a YYYY-MM-DD date"
            ) from None
    for key, kept in names.items():
        if key != fold(key) or not key:
            raise ValueError(f"The corrections name {key!r} is not a folded spelling")
        if not isinstance(kept, str) or not kept.strip():
            raise ValueError(f"The corrections name {key!r} keeps an empty name")
        if names.get(fold(kept), kept) != kept:
            raise ValueError(
                f"The corrections name {key!r} keeps {kept!r}, which is itself corrected"
            )
    return days, names


def _note(raw: str) -> list[str]:
    """The notes the source text carries, such as a player who left, as written."""
    return [
        tag for tag in re.findall(r"\(([^)]*)\)", raw) if _name(tag) not in RACE_TAGS
    ]


# The note of a series whose winner, known or not, does not play the next series
LEFT = "The winner does not play the next series"


def _near(pair: tuple[str, ...], following: tuple[str, ...]) -> bool:
    """Whether a name of the pair nearly matches one that plays next, a likely typo."""
    return any(
        SequenceMatcher(None, name, other).ratio() >= 0.8
        for name in pair
        for other in following
        if min(len(name), len(other)) >= 4
    )


def infer_winners(
    rows: list[dict[str, Any]], king: str | None
) -> list[tuple[int | None, str | None]]:
    """(inferred winner side, note) per BO1 of one bracket, in source order.

    Each series is read on its own, winner stays on: a written winner stands,
    else the side that plays the next series won it, and the reported king won
    the last. A hand note, a rematch next, a name close to one in the next
    series, or a last series without its king leaves only that series without
    a winner, with a note saying why. A series whose winner, written or not
    known, does not play the next series is noted LEFT.
    """
    if not rows:
        return []
    pairs = [(_name(row["player_1"]), _name(row["player_2"])) for row in rows]
    after = [*pairs[1:], ((_name(king),) if king else ())]
    read: list[tuple[int | None, str | None]] = []
    for index, (row, pair, following) in enumerate(
        zip(rows, pairs, after, strict=True)
    ):
        stays = [side for side, name in enumerate(pair, 1) if name in following]
        last = index == len(rows) - 1
        notes = _note(row["raw_text"])
        if row["winner"]:
            left = not last and _name(row["winner"]) not in following
            read.append((None, LEFT if left else None))
        elif notes:
            read.append((None, f"The old page notes: {'; '.join(notes)}"))
        elif last and not king:
            read.append((None, "The old page names no king for this bracket"))
        elif last and not stays:
            read.append((None, "The crowned player is not in the last series"))
        elif last or len(stays) == 1:
            read.append((stays[0], None))
        elif stays:
            note = "These two played again next, so the order does not show who won"
            read.append((None, note))
        elif _near(pair, following):
            note = "A name here is close to one in the next series; it may be the same player"
            read.append((None, note))
        else:
            read.append((None, LEFT))
    return read


def _month_day(label: str) -> tuple[int, int] | None:
    """The month and day of a label written as a month name and a day, no year."""
    found = re.fullmatch(r"([A-Za-z]+) (\d{1,2})", label.strip())
    if found is None or found[1] not in calendar.month_name[1:]:
        return None
    return list(calendar.month_name).index(found[1]), int(found[2])


def _between(month_day: tuple[int, int], after: date, before: date) -> date | None:
    """The one date with that month and day strictly between the two, if exactly one."""
    fits = []
    for year in range(after.year, before.year + 1):
        try:
            day = date(year, *month_day)
        except ValueError:
            continue
        if after < day < before:
            fits.append(day)
    return fits[0] if len(fits) == 1 else None


def record_days(
    records: list[dict[str, Any]], dates: dict[str, date] | None = None
) -> dict[str, date | None]:
    """The day of every record by source key: its own, a reviewed one, or page order's.

    A reviewed date from the corrections file dates an undated record first.
    A page lists its nights newest first. A label with a month and a day but no
    year takes the one date between the nearest dated records above and below
    it on the same page. Anything else without a date stays None.
    """
    days: dict[str, date | None] = {}
    reviewed = dates or {}
    pages: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        pages[record["source_url"]].append(record)
    for page in pages.values():
        page.sort(key=lambda record: record["source_order"])
        dated = [date.fromisoformat(r["date"]) if r["date"] else None for r in page]
        for index, record in enumerate(page):
            days[record["event_id"]] = dated[index] or reviewed.get(record["event_id"])
            month_day = _month_day(record["date_text"])
            if days[record["event_id"]] is not None or month_day is None:
                continue
            newer = next((d for d in reversed(dated[:index]) if d), None)
            older = next((d for d in dated[index + 1 :] if d), None)
            if newer is not None and older is not None:
                days[record["event_id"]] = _between(month_day, older, newer)
    return days


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
        checked.add(path.relative_to(directory).as_posix())
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


def _written(section: dict[str, Any]) -> list[str]:
    """Every name a bracket writes, in page order: sides, explicit winners, crowns."""
    played = [row for row in section["matches"] if row["record_type"] == "match"]
    return [
        *(
            name
            for row in played
            for name in (row["player_1"], row["player_2"], row["winner"])
            if name is not None
        ),
        *(crown["player"] for crown in section["crowns"]),
    ]


def import_capture(
    records: list[dict[str, Any]],
    *,
    apply: bool = False,
    corrections: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Dry-run by default; each new event commits atomically, and reruns never overwrite.

    Corrections change what is written to the archive, never the stored source record.
    """
    counts = validate(records)
    dates, names = read_corrections({} if corrections is None else corrections, records)
    written = [
        name
        for record in records
        for section in record["sections"]
        if section["kind"] == "bracket"
        for name in _written(section)
    ]
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
        days = record_days(records, dates)
        for record in sorted(
            records, key=lambda row: (row["date"] or "", row["event_id"])
        ):
            if record["event_id"] in mapping:
                continue
            with Session.begin() as session:
                event_id = _insert_event(
                    session, record, days[record["event_id"]], names
                )
            mapping[record["event_id"]] = event_id
            inserted += 1
    return {
        "mode": "apply" if apply else "dry_run",
        "counts": dict(counts),
        "corrected_dates": sum(record["event_id"] in dates for record in records),
        "corrected_names": sum(fold(name) in names for name in written),
        "inserted_events": inserted,
        "existing_events": sum(record["event_id"] in existing for record in records),
        "event_ids": mapping,
    }


def _insert_event(
    session: OrmSession,
    record: dict[str, Any],
    day: date | None,
    names: dict[str, str] | None = None,
) -> int:
    """Write one record; names maps a folded spelling to the name kept for it."""
    names = names or {}

    def kept(name: str) -> str:
        return names.get(fold(name), name)

    # A day the record does not carry puts the full date in the name, as dated labels do
    label = (
        f"{calendar.month_name[day.month]} {day.day}, {day.year}"
        if day is not None and not record["date"]
        else record["date_text"]
    )
    name = f"KOTH {label}"
    duplicate = 1
    while (
        session.scalar(select(col(Season.id)).where(col(Season.name) == name))
        is not None
    ):
        duplicate += 1
        name = f"KOTH {label} ({duplicate})"
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
        played = [row for row in section["matches"] if row["record_type"] == "match"]
        # One participant per folded name: kept, else last crown's, else first spelling
        spellings: dict[str, str] = {}
        for name in _written(section):
            spellings.setdefault(fold(name), name)
        spellings |= {
            fold(crown["player"]): crown["player"] for crown in section["crowns"]
        }
        spellings |= {
            fold(kept(name)): kept(name)
            for name in _written(section)
            if fold(name) in names
        }
        entrants: dict[str, EventEntrant] = {}

        def participant(
            name: str,
            entrants: dict[str, EventEntrant] = entrants,
            spellings: dict[str, str] = spellings,
            section_no: int = section_no,
            division: EventDivision = division,
        ) -> EventEntrant:
            name = fold(kept(name))
            if name not in entrants:
                person = HistoricalParticipant(
                    event_id=event_id,
                    source_key=f"{section_no}:{len(entrants) + 1}",
                    source_name=spellings[name],
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

        read = [
            row
            | {
                "player_1": kept(row["player_1"]),
                "player_2": kept(row["player_2"]),
                "winner": row["winner"] and kept(row["winner"]),
            }
            for row in played
        ]
        king_name = kept(section["crowns"][-1]["player"]) if section["crowns"] else None
        inferred = dict(
            zip(map(id, played), infer_winners(read, king_name), strict=True)
        )
        for ordinal, row in enumerate(section["matches"], 1):
            if row["record_type"] != "match":
                continue
            inferred_winner, review_note = inferred[id(row)]
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
                    inferred_winner=inferred_winner,
                    review_note=review_note,
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
    """The import command accepts only an explicit loopback Postgres URL, without overrides.

    A name like localhost can resolve anywhere, and libpq takes PGHOSTADDR or a
    PGSERVICE entry over the host, so each of those is refused too.
    """
    url = make_url(value)
    if (
        url.drivername != "postgresql+psycopg"
        or url.host not in {"127.0.0.1", "::1"}
        or url.query
        or os.environ.keys() & {"PGHOSTADDR", "PGSERVICE"}
    ):
        raise ValueError(
            "Use a loopback 127.0.0.1 or ::1 URL, no query, PGHOSTADDR or PGSERVICE"
        )
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--database-url", required=True, type=local_url)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--corrections", type=Path, help="reviewed dates and names")
    args = parser.parse_args()
    records = load_capture(args.capture)
    corrections = json.loads(args.corrections.read_text()) if args.corrections else None
    init_engine(args.database_url)
    report = import_capture(records, apply=args.apply, corrections=corrections)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
