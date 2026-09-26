"""The egress monitor: after each daily snapshot, the cycle's level and its Discord posts.

The builders are pure and return webhook payloads; `post` sends one and never fails the job.
An alert posts once per change of level, so the state row is read and written on every run.
"""

import calendar
import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Any

import requests
from sqlalchemy.orm import Session as OrmSession

from app.core.db import Session
from app.models.egress_ledger import EgressLedger
from app.models.egress_snapshot import EgressSnapshotResult, EgressWindow
from app.models.monitor_state import MonitorState
from app.models.types import utcnow
from app.services import egress, egress_chart
from app.services.egress_snapshot import BUDGET_MB_PER_DAY, unavailable, windows

log = logging.getLogger(__name__)

KEY = "egress"
CYCLE_START_DAY = 26  # the Supabase billing cycle starts on this day of each month, UTC
CAP_MB = 5000.0  # the organisation's egress cap per cycle; staging shares it
RED_MB = 0.9 * CAP_MB  # a projected cycle total above this alerts
AVERAGE_OVER = timedelta(hours=72)  # the recent rate the projection extends
TOP_ROUTES = 3
CHART_DAYS = 14  # the digest chart shows the windows of the last two weeks
CHART = "egress.png"

RED, AMBER, GREEN, BLUE = 0xD63232, 0xF0A04B, 0x36A64F, 0x4F95D8
SILENT = 1 << 12  # SUPPRESS_NOTIFICATIONS: the post shows without a notification
FOOTER = "Egress monitor · pg_stat_statements × 100 B per row"
JOBS_DOC = (
    "https://github.com/Warcraft-Gym/wc3-gym-backend/blob/main/docs/okf/api/jobs.md"
)
# Discord's embed limits: title, description, field name, field value, fields, footer, total
LIMITS = {"title": 256, "description": 4096, "name": 256, "value": 1024, "text": 2048}
MAX_FIELDS, MAX_TOTAL = 25, 6000


class Level(StrEnum):
    NORMAL = "normal"
    AMBER = "amber"  # the last window was over the daily budget; digest colour only
    RED = "red"  # the cycle is projected past RED_MB
    UNAVAILABLE = "unavailable"  # the snapshot could not run


ALERTING = {Level.RED, Level.UNAVAILABLE}


@dataclass(frozen=True)
class Cycle:
    start: datetime
    end: datetime

    @property
    def days(self) -> int:
        return (self.end - self.start).days


def cycle(now: datetime) -> Cycle:
    """The billing cycle `now` falls in: from day 26 of a month to day 26 of the next."""
    year, month = now.year, now.month
    if now.day < CYCLE_START_DAY:
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    start = datetime(year, month, CYCLE_START_DAY, tzinfo=UTC)
    days = calendar.monthrange(year, month)[1]
    return Cycle(start, start + timedelta(days=days))


@dataclass(frozen=True)
class Meters:
    now: datetime
    cycle: Cycle
    last: EgressWindow | None
    average_mb_per_day: float
    cycle_mb: float
    projected_mb: float
    history: tuple[EgressWindow, ...] = ()  # the windows read, oldest first

    @property
    def level(self) -> Level:
        if self.projected_mb > RED_MB:
            return Level.RED
        if self.last is not None and self.last.mb_per_day > BUDGET_MB_PER_DAY:
            return Level.AMBER
        return Level.NORMAL

    @property
    def day(self) -> int:
        return (self.now - self.cycle.start).days + 1


def meters(found: list[EgressWindow], now: datetime) -> Meters:
    """The cycle's figures from the windows read, oldest first; `history` keeps them all."""
    c = cycle(now)
    so_far = sum(w.estimated_mb for w in found if w.end >= c.start)
    recent = [w for w in found if w.end >= now - AVERAGE_OVER] or found[-1:]
    hours = sum(w.hours for w in recent)
    average = sum(w.estimated_mb for w in recent) / hours * 24 if hours else 0.0
    left = (c.end - now).total_seconds() / 86400
    return Meters(
        now=now,
        cycle=c,
        last=found[-1] if found else None,
        average_mb_per_day=average,
        cycle_mb=so_far,
        projected_mb=so_far + average * left,
        history=tuple(found),
    )


def mention_id() -> str | None:
    """DEV_ALERTS_MENTION_USER_ID when it is a Discord user id, digits only; else None."""
    value = os.getenv("DEV_ALERTS_MENTION_USER_ID", "").strip()
    return value if value.isascii() and value.isdigit() else None


# Text


def stamp(at: datetime, style: str = "f") -> str:
    return f"<t:{int(at.timestamp())}:{style}>"


def size(mb: float) -> str:
    return f"{mb / 1000:,.1f} GB" if mb >= 1000 else f"{mb:,.0f} MB"


def meter(value: float, whole: float) -> str:
    """Ten cells and the percentage; over 100% fills the bar and the figure says by how much."""
    pct = value / whole * 100
    k = max(0, min(10, round(pct / 10)))
    return f"`{'▰' * k}{'▱' * (10 - k)}` {pct:,.0f}%"


def duration(span: timedelta) -> str:
    days, hours = span.days, span.seconds // 3600
    if days:
        return f"{days} day{'s' * (days != 1)}"
    if hours:
        return f"{hours} hour{'s' * (hours != 1)}"
    return "under an hour"


def day_label(d: date) -> str:
    return f"{d.day} {d:%b}"


def route_lines(routes: list[EgressLedger], day: date) -> str:
    if not routes:
        return f"No ledger rows for {day_label(day)}."
    return "\n".join(
        f"`{r.method} {r.route}` {r.rows:,} rows · {r.calls:,} calls" for r in routes
    )


def rate(w: EgressWindow | None) -> str:
    return "none yet" if w is None else f"~{w.mb_per_day:,.0f} MB/day"


# Payloads


def field(name: str, value: str, inline: bool = True) -> dict[str, Any]:
    return {"name": name, "value": value, "inline": inline}


def cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def fit(embed: dict[str, Any]) -> dict[str, Any]:
    """The embed cut to Discord's limits; the description gives way when the total is over."""
    embed = {**embed, "title": cut(embed["title"], LIMITS["title"])}
    embed["fields"] = [
        {
            **f,
            "name": cut(f["name"], LIMITS["name"]),
            "value": cut(f["value"], LIMITS["value"]),
        }
        for f in embed.get("fields", [])[:MAX_FIELDS]
    ]
    embed["footer"] = {"text": cut(embed["footer"]["text"], LIMITS["text"])}
    rest = (
        len(embed["title"])
        + len(embed["footer"]["text"])
        + sum(len(f["name"]) + len(f["value"]) for f in embed["fields"])
    )
    room = min(LIMITS["description"], MAX_TOTAL - rest)
    embed["description"] = cut(embed.get("description", ""), max(room, 1))
    return embed


def message(
    now: datetime,
    colour: int,
    title: str,
    description: str,
    fields: list[dict[str, Any]],
    silent: bool = False,
    mention: str | None = None,
    image: str | None = None,
) -> dict[str, Any]:
    """One webhook payload with one embed; only an alert names `mention`, and pings no one else."""
    embed = fit(
        {
            "title": title,
            "description": description,
            "color": colour,
            "fields": fields,
            "timestamp": now.isoformat(),
            "footer": {"text": FOOTER},
        }
    )
    if image:
        embed["image"] = {"url": image}
    payload: dict[str, Any] = {"embeds": [embed]}
    if mention:
        payload["content"] = f"<@{mention}> egress needs action today"
        payload["allowed_mentions"] = {"users": [mention]}
    else:
        payload["allowed_mentions"] = {"parse": []}
    if silent:
        payload["flags"] = SILENT
    return payload


def alert(
    m: Meters, routes: list[EgressLedger], since: datetime, mention: str | None
) -> dict[str, Any]:
    """The red alert: the cycle is on track to pass the cap, or has passed it."""
    over = m.cycle_mb > CAP_MB
    title = f"Supabase egress: {'over' if over else 'on track to pass'} the 5 GB cap"
    budget = f"{BUDGET_MB_PER_DAY:,.0f} MB a day"
    lead = (
        f"Prod returned ~{m.last.mb_per_day:,.0f} MB a day in the last window, "
        f"{m.last.mb_per_day / BUDGET_MB_PER_DAY:,.1f}× the budget of {budget}. "
        if m.last is not None
        else ""
    )
    description = (
        f"{lead}The cycle is at {size(m.cycle_mb)} of 5 GB and is projected at "
        f"{size(m.projected_mb)} when it ends {stamp(m.cycle.end, 'R')}."
    )
    day = (m.now - timedelta(days=1)).date()
    fields = [
        field("Last window", rate(m.last)),
        field("3-day average", f"~{m.average_mb_per_day:,.0f} MB/day"),
        field("Budget", f"{BUDGET_MB_PER_DAY:,.0f} MB/day"),
        field(
            "Cycle so far",
            f"{meter(m.cycle_mb, CAP_MB)}\n{m.cycle_mb / 1000:,.1f} GB of 5 GB",
        ),
        field("Projected at cycle end", f"~{size(m.projected_mb)}"),
        field("Since", stamp(since)),
        field("Top routes (rows)", route_lines(routes, day), inline=False),
        field(
            "Next step",
            "Check who calls these routes with `just egress-routes 1`. "
            f"Stop any agent or script reading prod. [Egress jobs]({JOBS_DOC})",
            inline=False,
        ),
    ]
    return message(m.now, RED, title, description, fields, mention=mention)


def unavailable_alert(
    reason: str, now: datetime, mention: str | None
) -> dict[str, Any]:
    return message(
        now,
        RED,
        "Egress snapshot could not run",
        f"{reason}. The next run is due {stamp(now + timedelta(days=1), 'R')}.",
        [field("Since", stamp(now))],
        mention=mention,
    )


def recovery(m: Meters, was: str, since: datetime) -> dict[str, Any]:
    """The silent all-clear after a red or unavailable run."""
    title = (
        "Supabase egress: back under budget"
        if was == Level.RED
        else "Egress snapshot: running again"
    )
    description = (
        f"The last 3 days averaged ~{m.average_mb_per_day:,.0f} MB/day. "
        f"The cycle is projected at {size(m.projected_mb)} of 5 GB."
    )
    fields = [
        field("Last window", rate(m.last)),
        field("3-day average", f"~{m.average_mb_per_day:,.0f} MB/day"),
        field(
            f"{'Red' if was == Level.RED else 'Unavailable'} for",
            f"{duration(m.now - since)}, since {stamp(since)}",
        ),
    ]
    return message(m.now, GREEN, title, description, fields, silent=True)


STATUS = {
    Level.NORMAL: (BLUE, "All meters normal."),
    Level.AMBER: (AMBER, "Yesterday was over the daily budget."),
    Level.RED: (RED, "The cycle is on track to pass the cap."),
}


def digest(m: Meters, routes: list[EgressLedger]) -> dict[str, Any]:
    """The silent daily post with every meter; before the first window, the baseline note."""
    if m.last is None:
        return message(
            m.now,
            BLUE,
            f"Daily infrastructure digest · {day_label(m.now.date())}",
            "Baseline taken. First figures after the next run.",
            [],
            silent=True,
        )
    colour, status = STATUS[m.level]
    per_day = m.last.mb_per_day
    fields = [
        field(
            "Supabase egress, prod",
            f"~{per_day:,.0f} MB/day\n{meter(per_day, BUDGET_MB_PER_DAY)} of budget",
        ),
        field(
            "Cycle so far",
            f"~{size(m.cycle_mb)} of 5 GB\n{meter(m.cycle_mb, CAP_MB)}"
            f" · day {m.day} of {m.cycle.days}",
        ),
        field("Projected", f"~{size(m.projected_mb)}"),
        field(
            "Busiest routes (rows)",
            route_lines(routes, (m.now - timedelta(days=1)).date()),
            inline=False,
        ),
    ]
    title = f"Daily infrastructure digest · {day_label(m.last.end.date())}"
    image = f"attachment://{CHART}" if len(m.history) >= 2 else None
    return message(m.now, colour, title, status, fields, silent=True, image=image)


def posts(
    state: MonitorState | None,
    m: Meters,
    routes: list[EgressLedger],
    mention: str | None,
) -> list[dict[str, Any]]:
    """An alert on a change to red, a recovery on a change out of red or unavailable, then the digest."""
    was = state.level if state is not None else None
    out = []
    if m.level in ALERTING and m.level != was:
        out.append(alert(m, routes, m.now, mention))
    elif state is not None and was in ALERTING and m.level not in ALERTING:
        out.append(recovery(m, state.level, state.since))
    out.append(digest(m, routes))
    return out


# The run


def save(
    session: OrmSession, state: MonitorState | None, level: Level, now: datetime
) -> None:
    if state is None:
        session.add(MonitorState(key=KEY, level=level, since=now, updated_at=now))
        return
    if state.level != level:
        state.level, state.since = level, now
    state.updated_at = now


def report(result: EgressSnapshotResult, now: datetime | None = None) -> None:
    """Level the run, store the level and post what changed; a skipped run does nothing."""
    if result.skipped:
        return
    now = now or utcnow()
    mention = mention_id()
    history: tuple[EgressWindow, ...] = ()
    with Session.begin() as session:
        state = session.get(MonitorState, KEY)
        if not result.available:
            level = Level.UNAVAILABLE
            out = []
            if state is None or state.level != level:
                out = [unavailable_alert(result.reason or "unknown", now, mention)]
        else:
            since = min(cycle(now).start, now - timedelta(days=CHART_DAYS))
            m = meters(windows(session, since), now)
            level, history = m.level, m.history
            routes = egress.busiest(
                session, (now - timedelta(days=1)).date(), TOP_ROUTES
            )
            out = posts(state, m, routes, mention)
        save(session, state, level, now)
    if not os.getenv("DEV_ALERTS_WEBHOOK_URL"):
        return  # no channel: draw no chart
    for payload in out:
        post(*with_chart(payload, history))


def with_chart(
    payload: dict[str, Any], history: tuple[EgressWindow, ...]
) -> tuple[dict[str, Any], bytes | None]:
    """The payload and its chart when its embed shows one; on a render error, without the image."""
    embed = payload["embeds"][0]
    if "image" not in embed:
        return payload, None
    points = [(day_label(w.end.date()), w.mb_per_day) for w in history[-CHART_DAYS:]]
    try:
        return payload, egress_chart.render(points, BUDGET_MB_PER_DAY)
    except Exception as error:
        log.warning("egress chart not drawn: %s", type(error).__name__)
        rest = {k: v for k, v in embed.items() if k != "image"}
        return {**payload, "embeds": [rest]}, None


def crashed(reason: str, now: datetime | None = None) -> None:
    """The unavailable alert for a run that raised, once per change of level."""
    now = now or utcnow()
    try:
        report(unavailable(reason), now)
    except Exception:
        # The database may be what failed, so the alert posts without its state
        post(unavailable_alert(reason, now, mention_id()))


def post(payload: dict[str, Any], png: bytes | None = None) -> None:
    """Send one payload to the DEV_ALERTS_WEBHOOK_URL channel webhook, with the chart as an
    attachment when there is one; unset sends nothing."""
    url = os.getenv("DEV_ALERTS_WEBHOOK_URL")
    if not url:
        return
    try:
        if png is None:
            sent = requests.post(url, json=payload, timeout=10)
        else:
            sent = requests.post(
                url,
                data={"payload_json": json.dumps(payload)},
                files={"files[0]": (CHART, png, "image/png")},
                timeout=10,
            )
        sent.raise_for_status()
    except requests.RequestException as error:
        # The exception text carries the webhook URL and its token: log the type and status only
        status = error.response.status_code if error.response is not None else None
        log.warning("egress post not sent: %s %s", type(error).__name__, status)
