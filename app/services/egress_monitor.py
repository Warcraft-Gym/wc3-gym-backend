"""The egress monitor: after each daily snapshot, the cycle's level, the database size, the
Vercel usage and their Discord posts.

The builders are pure and return webhook payloads; `post` sends one and never fails the job.
An alert posts once per change of level, so each check's state row is read and written on every run.
"""

import calendar
import json
import logging
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import Any

import requests
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel import col, select

from app.core.db import Session
from app.models.egress_ledger import EgressLedger
from app.models.egress_snapshot import EgressSnapshotResult
from app.models.monitor_state import MonitorState
from app.models.types import utcnow
from app.services import egress
from app.services.egress import Day, day_of
from app.services.egress_snapshot import unavailable

log = logging.getLogger(__name__)

KEY = "egress"
CYCLE_START_DAY = 25  # the Supabase billing cycle starts on this day of each month, UTC
CAP_MB = 5000.0  # the organisation's egress cap per cycle; staging shares it
RED_MB = 0.9 * CAP_MB  # a projected cycle total above this alerts
AVERAGE_DAYS = 3  # the complete days whose mean the projection extends
TOP_ROUTES = 3
DB_KEY = "db_size"
DB_CAP_MB = 500.0  # the Supabase Free database size
DB_RED = 0.9  # a database over this share of DB_CAP_MB alerts
VERCEL_KEY = "vercel"
# The staging project shares the egress cap; Vercel runs crons on production only, so prod's run
# takes staging's snapshot through its own route and reads its windows back
STAGING_API = "https://wc3-gym-backend-git-main-wc-3-gym.vercel.app"
VERCEL_API = "https://api.vercel.com"
VERCEL_CREDIT_USD = 20.0  # Pro's monthly usage credit (vercel.com/docs/plans/pro-plan); past it, usage bills on demand
VERCEL_FEES = "Subscription Licenses"  # the charge category of plan and add-on fees, which is not usage
VERCEL_ROWS = 4  # the costliest services the digest lists; ISR Writes is always one
# Short names for the digest's narrow table; any other service keeps Vercel's name
VERCEL_NAMES = {
    "Fluid Active CPU": "Active CPU",
    "Fluid Provisioned Memory": "Memory",
    "Build CPU Minutes": "Build CPU",
    "Fast Data Transfer": "Data transfer",
    "Fast Origin Transfer": "Origin transfer",
}
# Vercel's units as the digest writes them, with their decimals; any other unit is a count
VERCEL_UNITS = {
    "hour": ("h", 2),
    "minute": ("min", 0),
    "gigabyte": ("GB", 2),
    "gigabyte-hour": ("GB-h", 1),
}

RED, AMBER, GREEN, BLUE = 0xD63232, 0xF1C40F, 0x36A64F, 0x4F95D8
SILENT = 1 << 12  # SUPPRESS_NOTIFICATIONS: the post shows without a notification
FOOTER = "Egress monitor · bytes measured on the database connections"
MONITOR_FOOTER = "Infrastructure monitor"
# The fields that give way first when an embed is over the total: the long route lists
# The digest's field names: a Supabase section, then a Vercel one
EGRESS_FIELD = "Supabase · egress"
DB_FIELD = "Supabase · database size (prod)"
ROUTES_FIELD = "Supabase · busiest routes (prod)"
VERCEL_FIELD = "Vercel · usage this billing period"
ROUTE_FIELDS = (ROUTES_FIELD, "Top routes")
JOBS_DOC = (
    "https://github.com/Warcraft-Gym/wc3-gym-backend/blob/main/docs/okf/api/jobs.md"
)
# Discord's embed limits: title, description, field name, field value, fields, footer, total
LIMITS = {"title": 256, "description": 4096, "name": 256, "value": 1024, "text": 2048}
MAX_FIELDS, MAX_TOTAL = 25, 6000


class Level(StrEnum):
    NORMAL = "normal"
    AMBER = "amber"  # over a daily budget or on pace past a credit; digest colour only
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
    """The billing cycle `now` falls in: from day 25 of a month to day 25 of the next."""
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
    last: Day | None  # the last complete day of prod
    average_mb_per_day: float
    cycle_mb: float
    projected_mb: float
    staging_mb: float | None = None  # staging's share of cycle_mb; None when not read
    staging_measured: bool = (
        True  # False while staging's ledger holds no measured bytes
    )
    partial: bool = False  # a day of the cycle ran statements but measured no bytes
    staging_last: Day | None = None  # staging on prod's last day; None when not read

    @property
    def budget_mb(self) -> float:
        """The cap spread evenly over the cycle's days."""
        return CAP_MB / self.cycle.days

    @property
    def day_mb(self) -> float | None:
        """Both projects' measured MB on the last complete day; None when neither measured."""
        days = [self.last, self.staging_last]
        measured = [d.mb for d in days if d is not None and d.mb is not None]
        return sum(measured) if measured else None

    @property
    def level(self) -> Level:
        if self.projected_mb > RED_MB:
            return Level.RED
        if (self.day_mb or 0) > self.budget_mb:
            return Level.AMBER
        return Level.NORMAL

    @property
    def unmeasured(self) -> bool:
        """The last complete day served statements but measured no bytes."""
        return self.last is not None and self.last.mb is None

    @property
    def covers(self) -> date:
        """The UTC day the posts report: the last complete day."""
        if self.last is None:
            return (self.now - timedelta(days=1)).date()
        return self.last.day

    @property
    def since(self) -> datetime:
        """When the current level began: the start of the day that set it."""
        return datetime.combine(self.covers, time(), UTC)

    @property
    def day(self) -> int:
        return (self.now - self.cycle.start).days + 1


def totals(found: list[Day], c: Cycle, now: datetime) -> tuple[float, float]:
    """One project's measured MB this cycle, today so far included, and the mean of its
    last complete measured days."""
    so_far = sum(d.mb or 0 for d in found if d.day >= c.start.date())
    complete = [d.mb for d in found if d.day < now.date() and d.mb is not None]
    recent = complete[-AVERAGE_DAYS:]
    return so_far, sum(recent) / len(recent) if recent else 0.0


def meters(found: list[Day], now: datetime, staging: list[Day] | None = None) -> Meters:
    """The cycle's figures from prod's measured days and staging's, each oldest first."""
    c = cycle(now)
    so_far, average = totals(found, c, now)
    staging_mb = None
    if staging is not None:
        staging_mb, staging_average = totals(staging, c, now)
        so_far, average = so_far + staging_mb, average + staging_average
    left = (c.end - now).total_seconds() / 86400
    complete = [d for d in found if d.day < now.date()]
    in_cycle = [d for d in [*found, *(staging or [])] if d.day >= c.start.date()]
    last = complete[-1] if complete else None
    staging_last = None
    if staging is not None and last is not None:
        # A day without a ledger row ran no statements: zero, not unknown
        staging_last = next(
            (d for d in staging if d.day == last.day), Day(last.day, 0.0)
        )
    return Meters(
        now=now,
        cycle=c,
        last=last,
        staging_last=staging_last,
        average_mb_per_day=average,
        cycle_mb=so_far,
        projected_mb=so_far + average * left,
        staging_mb=staging_mb,
        staging_measured=not staging or any(d.mb is not None for d in staging),
        partial=any(d.mb is None for d in in_cycle),
    )


def staging_days(since: date, now: datetime) -> list[Day] | None:
    """Staging's measured days from its own ledger; None off production or when staging
    did not answer."""
    if os.getenv("VERCEL_ENV") != "production":
        return None
    try:
        r = requests.get(
            f"{STAGING_API}/jobs/egress",
            params={"days": min((now.date() - since).days + 1, 90)},
            headers={"Authorization": f"Bearer {os.getenv('CRON_SECRET', '')}"},
            timeout=20,
        )
        r.raise_for_status()
        sums: dict[date, list[int]] = {}
        for row in r.json():
            total = sums.setdefault(date.fromisoformat(row["day"]), [0, 0])
            total[0] += row["statements"]
            total[1] += row.get("db_bytes", 0)
        return [day_of(d, *sums[d]) for d in sorted(sums)]
    except (requests.RequestException, ValueError, KeyError) as error:
        log.warning("staging egress not read: %s", type(error).__name__)
        return None


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
        f"`{r.method} {r.route}` {r.db_bytes / 1e6:,.1f} MB · {r.calls:,} calls"
        for r in routes
    )


def rate(d: Day | None) -> str:
    if d is None:
        return "none yet"
    return "not measured" if d.mb is None else f"{d.mb:,.0f} MB"


def table(rows: Sequence[tuple[str, ...]]) -> str:
    """Rows in a code block, the first column left-aligned and the rest right-aligned."""
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    lines = [
        "  ".join(
            c.ljust(w) if i == 0 else c.rjust(w)
            for i, (c, w) in enumerate(zip(r, widths))
        )
        for r in rows
    ]
    return "```\n" + "\n".join(line.rstrip() for line in lines) + "\n```"


def cell(mb: float | None) -> str:
    """A table figure; `-` is one the ledger did not measure."""
    return "-" if mb is None else size(mb)


def egress_lines(m: Meters, last: Day) -> str:
    """The cycle against the cap, then each project's last day and cycle so far over the
    budget: the cap, and the cap spread over the cycle's days. Both projects count."""
    prod, staging = last.mb, m.staging_last.mb if m.staging_last else None
    prod_cycle = m.cycle_mb - (m.staging_mb or 0)
    rows = [("", day_label(last.day), "Cycle"), ("Prod", cell(prod), cell(prod_cycle))]
    if m.staging_last is not None:
        staging_cycle = m.staging_mb if m.staging_measured else None
        rows.append(("Staging", cell(staging), cell(staging_cycle)))
    rows.append(("Total", cell(m.day_mb), size(m.cycle_mb)))
    rows.append(("Budget", size(m.budget_mb), size(CAP_MB)))
    notes = [
        (
            f"{meter(m.cycle_mb, CAP_MB)} of {size(CAP_MB)} · day {m.day} of {m.cycle.days}"
            f" · on pace for {size(m.projected_mb)}"
        ),
        table(rows),
    ]
    if m.staging_last is None:
        notes.append("Staging not read.")
    if m.partial or any("-" in r for r in rows):
        notes.append("Totals count measured figures only.")
    return "\n".join(notes)


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
    lead = (
        f"Egress was {m.day_mb:,.0f} MB on {day_label(m.covers)}, "
        f"{m.day_mb / m.budget_mb:,.1f}× the {m.budget_mb:,.0f} MB daily budget. "
        if m.day_mb is not None
        else ""
    )
    description = (
        f"{lead}The cycle is at {size(m.cycle_mb)} of 5 GB and is projected at "
        f"{size(m.projected_mb)} when it ends {stamp(m.cycle.end, 'R')}."
    )
    fields = [
        field(day_label(m.covers), rate(m.last)),
        field("3-day average", f"{m.average_mb_per_day:,.0f} MB/day"),
        field("Daily budget", f"{m.budget_mb:,.0f} MB/day"),
        field(
            "Cycle so far",
            f"{meter(m.cycle_mb, CAP_MB)}\n{m.cycle_mb / 1000:,.1f} GB of 5 GB",
        ),
        field("Projected at cycle end", f"~{size(m.projected_mb)}"),
        field("Since", stamp(since)),
        field("Top routes", route_lines(routes, m.covers), inline=False),
        field(
            "Next step",
            "Check who calls these routes with `just monitor routes prod`. "
            f"Stop any agent or script reading prod. [Egress jobs]({JOBS_DOC})",
            inline=False,
        ),
    ]
    return message(m.now, RED, title, description, fields, mention=mention, links=links)


def unavailable_alert(
    reason: str,
    now: datetime,
    mention: str | None,
    title: str = "Egress snapshot could not run",
) -> dict[str, Any]:
    return message(
        now,
        RED,
        title,
        f"{reason[:1].upper()}{reason[1:]}. The next run is due {stamp(now + timedelta(days=1), 'R')}.",
        [field("Since", stamp(now))],
        mention=mention,
    )


def recovery(m: Meters, was: str, since: datetime) -> dict[str, Any]:
    """The silent all-clear after a red or unavailable run."""
    title = (
        "Supabase egress: back on track for the 5 GB cap"
        if was == Level.RED
        else "Egress snapshot: running again"
    )
    description = (
        f"The last 3 days averaged {m.average_mb_per_day:,.0f} MB/day. "
        f"The cycle is projected at {size(m.projected_mb)} of 5 GB."
    )
    fields = [
        field(day_label(m.covers), rate(m.last)),
        field("3-day average", f"{m.average_mb_per_day:,.0f} MB/day"),
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
        field(DB_FIELD, db_line(mb)),
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
            field(DB_FIELD, db_line(mb)),
            field("Red for", f"{duration(now - since)}, since {stamp(since)}"),
        ],
        silent=True,
        footer=MONITOR_FOOTER,
    )


def db_line(mb: float) -> str:
    return f"{meter(mb, DB_CAP_MB)} of {DB_CAP_MB:,.0f} MB · {mb:,.0f} MB used"


def db_level(mb: float) -> Level:
    return Level.RED if mb > DB_RED * DB_CAP_MB else Level.NORMAL


@dataclass(frozen=True)
class Service:
    """One Vercel service's usage this billing period and what it drew from the credit."""

    name: str
    quantity: float
    unit: str
    usd: float

    @property
    def label(self) -> str:
        return VERCEL_NAMES.get(self.name, self.name)

    @property
    def amount(self) -> str:
        unit, decimals = VERCEL_UNITS.get(self.unit, ("", 0))
        return f"{self.quantity:,.{decimals}f} {unit}".rstrip()


@dataclass(frozen=True)
class Vercel:
    """The team's usage this billing period, from its charges; plan fees are not usage."""

    start: datetime
    end: datetime
    now: datetime
    used_usd: float  # usage, drawn from the credit first
    billed_usd: float  # usage charged past the credit
    projected_usd: float
    services: list[Service]  # costliest first
    # The share of CDN requests the cache answered; None with no requests
    hits: float | None

    @property
    def day(self) -> int:
        return (self.now - self.start).days + 1

    @property
    def days(self) -> int:
        return round((self.end - self.start).total_seconds() / 86400)

    @property
    def level(self) -> Level:
        """Amber past the credit or on pace for it: usage then bills on demand, nothing pauses."""
        if self.billed_usd >= 0.01 or self.projected_usd > VERCEL_CREDIT_USD:
            return Level.AMBER
        return Level.NORMAL


def usd(amount: float, cents: bool = True) -> str:
    return f"${amount:,.{2 if cents else 0}f}"


def vercel_lines(v: Vercel) -> str:
    """The credit used, then the costliest services with ISR Writes always among them."""
    shown = v.services[:VERCEL_ROWS]
    isr = next((s for s in v.services if s.name == "ISR Writes"), None)
    if isr is not None and isr not in shown:
        shown = [*shown[:-1], isr]
    rows = [("", "Period", "Cost"), *((s.label, s.amount, usd(s.usd)) for s in shown)]
    other = v.used_usd - sum(s.usd for s in shown)
    if other >= 0.005:
        rows.append(("Other", "", usd(other)))
    rows.append(("Used", "", usd(v.used_usd)))
    if v.billed_usd >= 0.01:
        rows.append(("On demand", "", usd(v.billed_usd)))
    rows.append(("Credit", "", usd(VERCEL_CREDIT_USD)))
    lines = [
        (
            f"{meter(v.used_usd, VERCEL_CREDIT_USD)} of the {usd(VERCEL_CREDIT_USD, False)} credit"
            f" · day {v.day} of {v.days} · on pace for {usd(v.projected_usd, False)}"
        ),
        table(rows),
    ]
    if v.hits is not None:
        lines.append(f"CDN cache hits: {v.hits:.0%} of requests")
    return "\n".join(lines)


def vercel_status(v: Vercel) -> str:
    if v.billed_usd >= 0.01:
        return f"Vercel usage is past the {usd(VERCEL_CREDIT_USD, False)} credit and billing on demand."
    return (
        f"Vercel usage is on pace to pass the {usd(VERCEL_CREDIT_USD, False)} credit."
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
    return message(
        now,
        GREEN,
        f"Vercel usage: {'read again' if was == Level.UNAVAILABLE else 'all clear'}",
        f"Usage this billing period is {usd(v.used_usd)} of the {usd(VERCEL_CREDIT_USD, False)} credit.",
        [
            field(VERCEL_FIELD, vercel_lines(v), inline=False),
            field(
                f"{'Red' if was == Level.RED else 'Unavailable'} for",
                f"{duration(now - since)}, since {stamp(since)}",
            ),
        ],
        silent=True,
        footer=MONITOR_FOOTER,
    )


STATUS = {
    Level.NORMAL: (BLUE, "All normal."),
    Level.AMBER: (AMBER, "Supabase egress was over its daily budget."),
    Level.RED: (RED, "Supabase egress is on track to pass the 5 GB cap."),
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
    """The silent daily post with every meter; before the first complete day, the baseline
    note. A red check turns it red, an amber one yellow, and the description names each."""
    db, usage, red, amber, note = [], [], [], [], []
    if db_mb is not None:
        db.append(field(DB_FIELD, db_line(db_mb), inline=False))
        if db_level(db_mb) == Level.RED:
            red.append("The database is near its size cap.")
    elif db_error is not None:
        db.append(field(DB_FIELD, f"not read ({db_error})", inline=False))
    if vercel is not None:
        usage.append(field(VERCEL_FIELD, vercel_lines(vercel), inline=False))
        if vercel.level == Level.AMBER:
            amber.append(vercel_status(vercel))
    elif vercel_error is not None:
        usage.append(field(VERCEL_FIELD, f"not read ({vercel_error})", inline=False))
    if m.last is None:
        fields = [*db, *usage]
        note.append("Baseline taken. First figures after the next run.")
        title = f"Daily infrastructure digest · {day_label(m.now.date())}"
    else:
        if m.level != Level.NORMAL:
            (red if m.level == Level.RED else amber).insert(0, STATUS[m.level][1])
        fields = [
            field(EGRESS_FIELD, egress_lines(m, m.last), inline=False),
            *db,
            field(ROUTES_FIELD, route_lines(routes, m.covers), inline=False),
            *usage,
        ]
        title = f"Daily infrastructure digest · {day_label(m.last.day)}"
    colour = RED if red else AMBER if amber else BLUE
    status = " ".join([*red, *amber, *note]) or STATUS[Level.NORMAL][1]
    return message(
        m.now,
        colour,
        title,
        status,
        fields,
        silent=True,
        links=links,
        footer=MONITOR_FOOTER,
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
    """The team's usage this billing period from the Vercel API: its charges and its CDN
    cache hits; UNAVAILABLE when the token is rejected; None when VERCEL_USAGE_TOKEN or
    VERCEL_TEAM_ID is unset. Any other failure raises to the run, which shows it in the digest."""
    token = os.getenv("VERCEL_USAGE_TOKEN", "").strip()
    team = os.getenv("VERCEL_TEAM_ID", "").strip()
    if not token or not team:
        return None

    def get(path: str, **params: str) -> requests.Response | None:
        response = requests.get(
            f"{VERCEL_API}{path}",
            params={"teamId": team, **params},
            headers={"Authorization": f"Bearer {token}"},
            timeout=20,
        )
        if response.status_code in (401, 403):
            log.warning(
                "vercel usage not read: token rejected %s", response.status_code
            )
            return None
        response.raise_for_status()
        return response

    found = get(f"/v2/teams/{team}")
    if found is None:
        return Level.UNAVAILABLE
    period = found.json()["billing"]["period"]
    start, end = (
        datetime.fromtimestamp(period[k] / 1000, UTC) for k in ("start", "end")
    )
    # The usage API answers 400 for a `to` in the future
    window = {"from": iso_ms(start), "to": iso_ms(now - timedelta(minutes=1))}
    charges = get("/v1/billing/charges", **window)
    cdn = get("/v2/usage", type="requests", **window)
    if charges is None or cdn is None:
        return Level.UNAVAILABLE
    # One JSON line per service, project, region and day
    rows = [json.loads(line) for line in charges.text.splitlines() if line.strip()]
    usage = [r for r in rows if r["ServiceCategory"] != VERCEL_FEES]
    totals: dict[str, list[Any]] = {}
    by_day: dict[datetime, float] = {}
    for r in usage:
        cost = r["EffectiveCost"] or 0
        total = totals.setdefault(r["ServiceName"], [0, r["ConsumedUnit"] or "", 0])
        total[0] += r["ConsumedQuantity"] or 0
        total[2] += cost
        day_end = datetime.fromisoformat(r["ChargePeriodEnd"])
        by_day[day_end] = by_day.get(day_end, 0) + cost
    services = sorted(
        (Service(name, *total) for name, total in totals.items() if total[2] > 0),
        key=lambda s: -s.usd,
    )
    used = sum(s.usd for s in services)
    complete = [by_day[d] for d in sorted(by_day) if d <= now][-AVERAGE_DAYS:]
    average = sum(complete) / len(complete) if complete else 0.0
    left = (end - max(by_day, default=start)).total_seconds() / 86400
    days = cdn.json()["data"]
    hit = sum(d.get("request_hit_count") or 0 for d in days)
    miss = sum(d.get("request_miss_count") or 0 for d in days)
    return Vercel(
        start=start,
        end=end,
        now=now,
        used_usd=used,
        billed_usd=sum(r["BilledCost"] or 0 for r in usage),
        projected_usd=used + average * max(left, 0),
        services=services,
        hits=hit / (hit + miss) if hit + miss else None,
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
    start = min(
        cycle(now).start.date(), (now - timedelta(days=AVERAGE_DAYS + 1)).date()
    )
    staging = staging_days(start, now)
    changes: list[Change] = []
    out: dict[str, Any] | None = None
    with Session() as session:
        keys = [KEY, DB_KEY, VERCEL_KEY]
        found = session.scalars(
            select(MonitorState).where(col(MonitorState.key).in_(keys))
        )
        states = {s.key: s for s in found}
        state = states.get(KEY)
        m = meters(egress.daily(session, start), now, staging)
        routes = egress.busiest(session, m.covers, TOP_ROUTES)
        if m.unmeasured or not result.available:
            reason, title = (
                (
                    f"the ledger measured no bytes for {day_label(m.covers)}",
                    "Egress not measured",
                )
                if m.unmeasured
                else (result.reason or "unknown", "Egress snapshot could not run")
            )
            changes.append(
                change(
                    state,
                    KEY,
                    Level.UNAVAILABLE,
                    now,
                    lambda: unavailable_alert(reason, now, mention, title),
                )
            )
        else:
            level, since = m.level, m.since
            if m.partial and state is not None and state.level == Level.RED:
                # A partly measured cycle reads low, so it never gives the all-clear
                level, since = Level.RED, state.since
            changes.append(
                change(
                    state,
                    KEY,
                    level,
                    since,
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
                    dict,  # never called: Vercel is never red, past the credit usage bills on demand
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
