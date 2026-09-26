"""The egress monitor: after each daily snapshot, the cycle's level, the database size, the
Vercel usage and their Discord posts.

The builders are pure and return webhook payloads; `post` sends one and never fails the job.
An alert posts once per change of level, so each check's state row is read and written on every run.
"""

import calendar
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Any

import requests
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel import col, select

from app.core.db import Session
from app.models.egress_ledger import EgressLedger
from app.models.egress_snapshot import EgressSnapshotResult, EgressWindow
from app.models.monitor_state import MonitorState
from app.models.types import utcnow
from app.services import egress
from app.services.egress_snapshot import BUDGET_MB_PER_DAY, unavailable, windows

log = logging.getLogger(__name__)

KEY = "egress"
CYCLE_START_DAY = 26  # the Supabase billing cycle starts on this day of each month, UTC
CAP_MB = 5000.0  # the organisation's egress cap per cycle; staging shares it
RED_MB = 0.9 * CAP_MB  # a projected cycle total above this alerts
AVERAGE_OVER = timedelta(hours=72)  # the recent rate the projection extends
TOP_ROUTES = 3
DB_KEY = "db_size"
DB_CAP_MB = 500.0  # the Supabase Free database size
DB_RED = 0.9  # a database over this share of DB_CAP_MB alerts
VERCEL_KEY = "vercel"
VERCEL_USAGE_API = "https://api.vercel.com/v2/usage"
# Hobby has no billing cycle: its limits hold over a rolling 30 days
VERCEL_WINDOW = timedelta(days=30)
VERCEL_INVOCATIONS = 1_000_000  # Vercel Hobby included usage, rolling 30 days
VERCEL_GB_HOURS = 360.0  # Hobby's Provisioned Memory (vercel.com/docs/functions/usage-and-pricing); the API's gb_hours may count less
VERCEL_REQUESTS = 1_000_000  # Vercel Hobby included usage, rolling 30 days
VERCEL_BANDWIDTH_GB = 100.0  # Vercel Hobby included usage, rolling 30 days
VERCEL_RED = 0.8  # any meter at this share of its included usage alerts

RED, AMBER, GREEN, BLUE = 0xD63232, 0xF0A04B, 0x36A64F, 0x4F95D8
SILENT = 1 << 12  # SUPPRESS_NOTIFICATIONS: the post shows without a notification
FOOTER = "Egress monitor · pg_stat_statements × 100 B per row"
DIGEST_FOOTER = (
    "Infrastructure monitor · egress from pg_stat_statements × 100 B per row"
)
MONITOR_FOOTER = "Infrastructure monitor"
# The fields that give way first when an embed is over the total: the long route lists
ROUTE_FIELDS = ("Busiest routes (rows)", "Top routes (rows)")
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

    @property
    def level(self) -> Level:
        if self.projected_mb > RED_MB:
            return Level.RED
        if self.last is not None and self.last.mb_per_day > BUDGET_MB_PER_DAY:
            return Level.AMBER
        return Level.NORMAL

    @property
    def covers(self) -> date:
        """The UTC day the last window covers; the ledger day the posts list."""
        if self.last is None:
            return (self.now - timedelta(days=1)).date()
        return self.last.start.date()

    @property
    def since(self) -> datetime:
        """When the current level began: the start of the window that set it."""
        return self.last.start if self.last is not None else self.now

    @property
    def day(self) -> int:
        return (self.now - self.cycle.start).days + 1


def meters(found: list[EgressWindow], now: datetime) -> Meters:
    """The cycle's figures from the windows read, oldest first."""
    c = cycle(now)
    # The 00:00 run's window covers the day before, so a window counts in the cycle it starts in
    so_far = sum(w.estimated_mb for w in found if w.start >= c.start)
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
    )


# The dashboards a post links to, by label, from their optional variables
DASHBOARDS = {
    "Supabase usage": "DEV_ALERTS_SUPABASE_USAGE_URL",
    "Vercel usage": "DEV_ALERTS_VERCEL_USAGE_URL",
}


def dashboards() -> dict[str, str]:
    """The dashboard links that are set to an https URL; anything else is ignored."""
    links = {label: os.getenv(name, "").strip() for label, name in DASHBOARDS.items()}
    return {label: url for label, url in links.items() if url.startswith("https://")}


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
    # Fields over the total on their own: the route list gives way first, cut or dropped
    for f in [f for f in embed["fields"] if f["name"] in ROUTE_FIELDS]:
        over = rest - (MAX_TOTAL - 1)
        if over <= 0:
            break
        if len(f["value"]) - over > 1:
            f["value"] = cut(f["value"], len(f["value"]) - over)
            rest -= over
        else:
            embed["fields"].remove(f)
            rest -= len(f["name"]) + len(f["value"])
    # Then drop trailing fields, always keeping the first
    while rest > MAX_TOTAL - 1 and len(embed["fields"]) > 1:
        dropped = embed["fields"].pop()
        rest -= len(dropped["name"]) + len(dropped["value"])
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
    links: dict[str, str] | None = None,
    ask: str = "egress needs action today",
    footer: str = FOOTER,
) -> dict[str, Any]:
    """One webhook payload with one embed; only an alert names `mention`, and pings no one else.
    `links` titles the embed with the Supabase usage page and lists every dashboard last."""
    links = links or {}
    if links:
        listed = " · ".join(f"[{label}]({url})" for label, url in links.items())
        fields = [*fields, field("Dashboards", listed, inline=False)]
    embed = fit(
        {
            "title": title,
            "description": description,
            "color": colour,
            "fields": fields,
            "timestamp": now.isoformat(),
            "footer": {"text": footer},
        }
    )
    if "Supabase usage" in links:
        embed["url"] = links["Supabase usage"]
    payload: dict[str, Any] = {"embeds": [embed]}
    if mention:
        payload["content"] = f"<@{mention}> {ask}"
        payload["allowed_mentions"] = {"users": [mention]}
    else:
        payload["allowed_mentions"] = {"parse": []}
    if silent:
        payload["flags"] = SILENT
    return payload


def alert(
    m: Meters,
    routes: list[EgressLedger],
    since: datetime,
    mention: str | None,
    links: dict[str, str] | None = None,
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
        field("Top routes (rows)", route_lines(routes, m.covers), inline=False),
        field(
            "Next step",
            "Check who calls these routes with `just egress-routes 1`. "
            f"Stop any agent or script reading prod. [Egress jobs]({JOBS_DOC})",
            inline=False,
        ),
    ]
    return message(m.now, RED, title, description, fields, mention=mention, links=links)


def unavailable_alert(
    reason: str, now: datetime, mention: str | None
) -> dict[str, Any]:
    return message(
        now,
        RED,
        "Egress snapshot could not run",
        f"{reason[:1].upper()}{reason[1:]}. The next run is due {stamp(now + timedelta(days=1), 'R')}.",
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


def db_alert(
    mb: float, now: datetime, mention: str | None, links: dict[str, str] | None = None
) -> dict[str, Any]:
    """The red alert: the database is over DB_RED of its size cap."""
    description = (
        f"The database is at ~{mb:,.0f} MB, {mb / DB_CAP_MB * 100:,.0f}% of the "
        f"{DB_CAP_MB:,.0f} MB cap."
    )
    fields = [
        field("Database size", db_line(mb)),
        field("Since", stamp(now)),
        field(
            "Next step",
            "Check the largest tables in Supabase Studio and delete or archive rows "
            f"before the cap. [Egress jobs]({JOBS_DOC})",
            inline=False,
        ),
    ]
    title = f"Supabase database size: near the {DB_CAP_MB:,.0f} MB cap"
    return message(
        now,
        RED,
        title,
        description,
        fields,
        mention=mention,
        links=links,
        ask="the database needs action today",
        footer=MONITOR_FOOTER,
    )


def db_recovery(mb: float, since: datetime, now: datetime) -> dict[str, Any]:
    """The silent all-clear after the database was red."""
    return message(
        now,
        GREEN,
        f"Supabase database size: back under {DB_RED:.0%} of the cap",
        f"The database is at ~{mb:,.0f} MB of {DB_CAP_MB:,.0f} MB.",
        [
            field("Database size", db_line(mb)),
            field("Red for", f"{duration(now - since)}, since {stamp(since)}"),
        ],
        silent=True,
        footer=MONITOR_FOOTER,
    )


def db_line(mb: float) -> str:
    return f"~{mb:,.0f} MB of {DB_CAP_MB:,.0f} MB\n{meter(mb, DB_CAP_MB)}"


def db_level(mb: float) -> Level:
    return Level.RED if mb > DB_RED * DB_CAP_MB else Level.NORMAL


@dataclass(frozen=True)
class Vercel:
    """The team's usage summed over the rolling window."""

    invocations: int
    gb_hours: float
    requests: int
    hits: int
    bandwidth_bytes: int

    @property
    def meters(self) -> list[tuple[str, str, float]]:
        """Each meter's label, figure and share of its included usage."""
        gb = self.bandwidth_bytes / 1e9
        return [
            (
                "Invocations",
                f"{self.invocations:,}",
                self.invocations / VERCEL_INVOCATIONS,
            ),
            (
                "Function GB-hours",
                f"{self.gb_hours:,.1f}",
                self.gb_hours / VERCEL_GB_HOURS,
            ),
            ("Requests", f"{self.requests:,}", self.requests / VERCEL_REQUESTS),
            ("Bandwidth", f"{gb:,.2f} GB", gb / VERCEL_BANDWIDTH_GB),
        ]

    @property
    def high(self) -> list[str]:
        """The meters at VERCEL_RED or over, each with its share."""
        return [
            f"{label} at {share:.0%}"
            for label, _, share in self.meters
            if share >= VERCEL_RED
        ]

    @property
    def level(self) -> Level:
        return Level.RED if self.high else Level.NORMAL


def vercel_lines(v: Vercel) -> str:
    lines = [f"{label} {figure} · {share:.0%}" for label, figure, share in v.meters]
    if v.requests:
        lines.append(f"Cache hits {v.hits / v.requests:.0%}")
    return "\n".join(lines)


def vercel_alert(
    v: Vercel, now: datetime, mention: str | None, links: dict[str, str] | None = None
) -> dict[str, Any]:
    """The red alert: a meter is at VERCEL_RED of its included usage."""
    description = (
        f"{' and '.join(v.high)} of the included usage over the last 30 days. "
        "Hobby pauses the feature for 30 days when a limit is hit."
    )
    fields = [
        field("Vercel, 30 days", vercel_lines(v), inline=False),
        field("Since", stamp(now)),
        field(
            "Next step",
            "Check which routes and functions drive the meter in the Vercel usage page. "
            f"[Egress jobs]({JOBS_DOC})",
            inline=False,
        ),
    ]
    return message(
        now,
        RED,
        "Vercel usage: near the included limit",
        description,
        fields,
        mention=mention,
        links=links,
        ask="Vercel usage needs action today",
        footer=MONITOR_FOOTER,
    )


def vercel_rejected_alert(
    now: datetime, mention: str | None, links: dict[str, str] | None = None
) -> dict[str, Any]:
    """The token alert; it links the Vercel usage dashboard when that is set."""
    links = links or {}
    vercel = {k: v for k, v in links.items() if k == "Vercel usage"}
    return message(
        now,
        RED,
        "Vercel usage could not be read: token rejected",
        "Vercel refused the token: it expired or was revoked. "
        "Set `VERCEL_USAGE_TOKEN` to a new token scoped to the team.",
        [field("Since", stamp(now))],
        mention=mention,
        links=vercel,
        ask="Vercel usage needs action today",
        footer=MONITOR_FOOTER,
    )


def vercel_recovery(
    v: Vercel, was: str, since: datetime, now: datetime
) -> dict[str, Any]:
    """The silent all-clear after the usage was red or could not be read."""
    red = was == Level.RED
    return message(
        now,
        GREEN,
        f"Vercel usage: {f'back under {VERCEL_RED:.0%}' if red else 'read again'}",
        f"Every meter is under {VERCEL_RED:.0%} of its included usage.",
        [
            field("Vercel, 30 days", vercel_lines(v), inline=False),
            field(
                f"{'Red' if red else 'Unavailable'} for",
                f"{duration(now - since)}, since {stamp(since)}",
            ),
        ],
        silent=True,
        footer=MONITOR_FOOTER,
    )


STATUS = {
    Level.NORMAL: (BLUE, "All meters normal."),
    Level.AMBER: (AMBER, "Yesterday was over the daily budget."),
    Level.RED: (RED, "The cycle is on track to pass the cap."),
}


def digest(
    m: Meters,
    routes: list[EgressLedger],
    links: dict[str, str] | None = None,
    db_mb: float | None = None,
    db_error: str | None = None,
    vercel: Vercel | None = None,
    vercel_error: str | None = None,
) -> dict[str, Any]:
    """The silent daily post with every meter; before the first window, the baseline note.
    The database size and the Vercel usage show when they were read or their read failed,
    and a red one turns the
    digest red."""
    extra, alarms = [], []
    if db_mb is not None:
        extra.append(field("Database size", db_line(db_mb)))
        if db_level(db_mb) == Level.RED:
            alarms.append("The database is near its size cap.")
    elif db_error is not None:
        extra.append(field("Database size", f"not read ({db_error})"))
    if vercel is not None:
        extra.append(field("Vercel, 30 days", vercel_lines(vercel), inline=False))
        if vercel.level == Level.RED:
            alarms.append("Vercel usage is near the included limit.")
    elif vercel_error is not None:
        extra.append(
            field("Vercel, 30 days", f"not read ({vercel_error})", inline=False)
        )
    if m.last is None:
        return message(
            m.now,
            RED if alarms else BLUE,
            f"Daily infrastructure digest · {day_label(m.now.date())}",
            " ".join([*alarms, "Baseline taken. First figures after the next run."]),
            extra,
            silent=True,
            links=links,
            footer=DIGEST_FOOTER,
        )
    colour, status = STATUS[m.level]
    if alarms:
        lead = [] if m.level == Level.NORMAL else [status]
        colour, status = RED, " ".join([*lead, *alarms])
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
        *extra,
        field(
            "Busiest routes (rows)",
            route_lines(routes, m.covers),
            inline=False,
        ),
    ]
    title = f"Daily infrastructure digest · {day_label(m.last.start.date())}"
    return message(
        m.now,
        colour,
        title,
        status,
        fields,
        silent=True,
        links=links,
        footer=DIGEST_FOOTER,
    )


# The run


@dataclass(frozen=True)
class Change:
    """One check's run: the level it measured, since when, and its post when the level changed."""

    key: str
    level: Level
    since: datetime
    alerting: bool  # the level changed into ALERTING, so `post` is an alert
    post: dict[str, Any] | None


def change(
    state: MonitorState | None,
    key: str,
    level: Level,
    since: datetime,
    alert: Callable[[], dict[str, Any]],
    recover: Callable[[MonitorState], dict[str, Any]] | None = None,
) -> Change:
    """An alert on a change into red or unavailable, a recovery on a change out of them."""
    was = state.level if state is not None else None
    if level in ALERTING and level != was:
        return Change(key, level, since, True, alert())
    if recover and state is not None and was in ALERTING and level not in ALERTING:
        return Change(key, level, since, False, recover(state))
    return Change(key, level, since, False, None)


def database_mb() -> float | None:
    """The size in MB (MiB, as Supabase counts it) of every database on the server but the
    templates, or of this one when the role may not read the others; None on SQLite."""
    every = (
        "SELECT sum(pg_database_size(datname)) FROM pg_database WHERE NOT datistemplate"
    )
    for query in (every, "SELECT pg_database_size(current_database())"):
        try:
            with Session() as session:
                if session.get_bind().dialect.name != "postgresql":
                    return None
                total = session.execute(text(query)).scalar_one()
            return None if total is None else int(total) / (1024 * 1024)
        except DBAPIError as error:
            # 42501, insufficient_privilege: one more try on the current database only
            if getattr(error.orig, "sqlstate", None) != "42501" or query != every:
                raise
            log.warning(
                "database size of every database not read: %s", type(error).__name__
            )
    return None


def vercel_usage(now: datetime) -> Vercel | Level | None:
    """The team's usage over the rolling window from the Vercel API; UNAVAILABLE when the
    token is rejected; None when VERCEL_USAGE_TOKEN or VERCEL_TEAM_ID is unset. Any other
    failure raises to the run, which shows it in the digest."""
    token = os.getenv("VERCEL_USAGE_TOKEN", "").strip()
    team = os.getenv("VERCEL_TEAM_ID", "").strip()
    if not token or not team:
        return None
    # The API answers 400 for a `to` in the future or a range over 31 days
    end = now - timedelta(minutes=1)
    params = {
        "teamId": team,
        "type": "requests",
        "from": iso_ms(end - VERCEL_WINDOW),
        "to": iso_ms(end),
    }
    response = requests.get(
        VERCEL_USAGE_API,
        params=params,
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    if response.status_code in (401, 403):
        log.warning("vercel usage not read: token rejected %s", response.status_code)
        return Level.UNAVAILABLE
    response.raise_for_status()
    days = response.json()["data"]
    total = {name: sum(day.get(name) or 0 for day in days) for name in VERCEL_FIELDS}
    return Vercel(
        invocations=int(sum(total[f"function_invocation_{k}_count"] for k in OUTCOMES)),
        gb_hours=float(
            sum(total[f"function_execution_{k}_gb_hours"] for k in OUTCOMES[:3])
        ),
        requests=int(total["request_hit_count"] + total["request_miss_count"]),
        hits=int(total["request_hit_count"]),
        # In and out: https://vercel.com/docs/manage-cdn-usage#calculating-fast-data-transfer
        bandwidth_bytes=int(
            total["bandwidth_incoming_bytes"] + total["bandwidth_outgoing_bytes"]
        ),
    )


OUTCOMES = ("successful", "error", "timeout", "throttle")
VERCEL_FIELDS = (
    *(f"function_invocation_{k}_count" for k in OUTCOMES),
    *(f"function_execution_{k}_gb_hours" for k in OUTCOMES[:3]),
    "request_hit_count",
    "request_miss_count",
    "bandwidth_incoming_bytes",
    "bandwidth_outgoing_bytes",
)


def iso_ms(at: datetime) -> str:
    """An ISO 8601 UTC time to the millisecond, as the Vercel API takes it."""
    return at.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def save(key: str, level: Level, since: datetime, now: datetime) -> None:
    """Store the level; `since` moves only when the level changes."""
    with Session.begin() as session:
        state = session.get(MonitorState, key)
        if state is None:
            session.add(MonitorState(key=key, level=level, since=since, updated_at=now))
            return
        if state.level != level:
            state.level, state.since = level, since
        state.updated_at = now


def report(result: EgressSnapshotResult, now: datetime | None = None) -> None:
    """Level each check, post what changed, then the digest, and store the levels; a skipped
    run does nothing.

    An alert that is not delivered leaves its check's stored level as it was, so the next run
    retries it. A database size that could not be read leaves its row alone.
    """
    if result.skipped:
        return
    now = now or utcnow()
    mention = mention_id()
    links = dashboards()
    db_error = vercel_error = None
    try:
        db_mb = database_mb()
    except Exception as error:
        # A read that keeps failing shows in the digest; the log line carries the type only
        db_mb, db_error = None, type(error).__name__
        log.warning("database size not read: %s", db_error)
    try:
        usage = vercel_usage(now)
    except Exception as error:
        # The type and HTTP status only: the error text may carry the request and its token
        status = getattr(getattr(error, "response", None), "status_code", None)
        name = type(error).__name__
        usage, vercel_error = None, f"{name} {status}" if status else name
        log.warning("vercel usage not read: %s", vercel_error)
    vercel = usage if isinstance(usage, Vercel) else None
    changes: list[Change] = []
    out: dict[str, Any] | None = None
    with Session() as session:
        keys = [KEY, DB_KEY, VERCEL_KEY]
        found = session.scalars(
            select(MonitorState).where(col(MonitorState.key).in_(keys))
        )
        states = {s.key: s for s in found}
        state = states.get(KEY)
        if not result.available:
            reason = result.reason or "unknown"
            changes.append(
                change(
                    state,
                    KEY,
                    Level.UNAVAILABLE,
                    now,
                    lambda: unavailable_alert(reason, now, mention),
                )
            )
        else:
            start = min(cycle(now).start, now - AVERAGE_OVER)
            m = meters(windows(session, start), now)
            routes = egress.busiest(session, m.covers, TOP_ROUTES)
            changes.append(
                change(
                    state,
                    KEY,
                    m.level,
                    m.since,
                    lambda: alert(m, routes, m.since, mention, links),
                    lambda s: recovery(m, s.level, s.since),
                )
            )
            out = digest(m, routes, links, db_mb, db_error, vercel, vercel_error)
        if db_mb is not None:
            mb = db_mb
            changes.append(
                change(
                    states.get(DB_KEY),
                    DB_KEY,
                    db_level(mb),
                    now,
                    lambda: db_alert(mb, now, mention, links),
                    lambda s: db_recovery(mb, s.since, now),
                )
            )
        if vercel is not None:
            v = vercel
            changes.append(
                change(
                    states.get(VERCEL_KEY),
                    VERCEL_KEY,
                    v.level,
                    now,
                    lambda: vercel_alert(v, now, mention, links),
                    lambda s: vercel_recovery(v, s.level, s.since, now),
                )
            )
        elif usage == Level.UNAVAILABLE:
            changes.append(
                change(
                    states.get(VERCEL_KEY),
                    VERCEL_KEY,
                    Level.UNAVAILABLE,
                    now,
                    lambda: vercel_rejected_alert(now, mention, links),
                )
            )
    for c in changes:
        delivered = post(c.post) if c.post is not None else True
        if delivered or not c.alerting:
            save(c.key, c.level, c.since, now)
    if out is not None:
        post(out)


def crashed(reason: str, now: datetime | None = None) -> None:
    """The unavailable alert for a run that raised, once per change of level."""
    now = now or utcnow()
    try:
        report(unavailable(reason), now)
    except Exception:
        # The database may be what failed, so the alert posts without its state
        post(unavailable_alert(reason, now, mention_id()))


def post(payload: dict[str, Any]) -> bool:
    """Send one payload to the DEV_ALERTS_WEBHOOK_URL channel webhook; True when Discord
    took it, False when the webhook is unset or the post failed."""
    url = os.getenv("DEV_ALERTS_WEBHOOK_URL")
    if not url:
        return False
    try:
        requests.post(url, json=payload, timeout=10).raise_for_status()
        return True
    except requests.RequestException as error:
        # The exception text carries the webhook URL and its token: log the type and status only
        status = error.response.status_code if error.response is not None else None
        log.warning("egress post not sent: %s %s", type(error).__name__, status)
        return False
