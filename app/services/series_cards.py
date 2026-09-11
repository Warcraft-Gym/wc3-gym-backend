"""The Discord cards about series: the match card /announce posts, the claim
card, the reminder and the /upcoming reply. A player reads
{flag} {name} ({race} {mmr}), and the footer says when the W3C MMR was synced."""

import os
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, time
from typing import Any, NamedTuple

from sqlalchemy import func, select
from sqlmodel import col

from app.core.db import Session
from app.models.enums import Race
from app.models.map import Map
from app.models.relationships import DBSeasonRound
from app.models.series import SeriesPublic
from app.models.types import utcnow
from app.models.user import User, UserPublic
from app.services import discord
from app.services.commands.base import (
    cast_link,
    emoji,
    flag,
    md,
    player_url,
    team_name,
)
from app.services.commands.veto import board_link, ping
from app.services.ladder import mmr_on
from app.services.series_veto import DEFAULT_RULES, SeriesVetoService

COLOR = 0x4A4DB8
# Discord takes 6000 characters over a message's embeds and 4096 in one description
BUDGET, DESCRIPTION = 5500, 4000


class Ratings(NamedTuple):
    """Each player's latest synced MMR per race, and the oldest sync among them."""

    mmr: dict[tuple[int, Race | None], int]
    synced: datetime | None


def ratings(rows: Sequence[SeriesPublic]) -> Ratings:
    ids = sorted({p.id for s in rows for p in (s.player1, s.player2) if p})
    if not ids:
        return Ratings({}, None)
    with Session() as session:
        mmr = mmr_on(session, ids, utcnow())
        synced = session.scalar(
            select(func.min(col(User.ladder_synced_at))).where(col(User.id).in_(ids))
        )
    if synced and synced.tzinfo is None:
        synced = synced.replace(tzinfo=UTC)
    return Ratings(mmr, synced)


def _name(user: UserPublic | None) -> str:
    return md((user.name if user else None) or "?")


def player(user: UserPublic | None, race: str | None, marks: Ratings) -> str:
    """{flag} {name} ({race} {mmr}). The name links to the GNL profile; "?" is
    an MMR the sync has not seen on that race. A link label keeps the name
    unescaped: Discord shows a backslash inside a label as typed."""
    if user is None:
        return "?"
    url = player_url(user)
    name = f"**[{user.name or '?'}](<{url}>)**" if url else f"**{_name(user)}**"
    line = f"{flag(user.country)} {name}".strip()
    if race:
        mmr = marks.mmr.get((user.id, Race(race)), "?")
        line += f" ({emoji(f'race_{race.lower()}') or race} {mmr})"
    return line


def players(series: SeriesPublic, marks: Ratings) -> str:
    one = player(series.player1, series.player1_race, marks)
    return f"{one} vs {player(series.player2, series.player2_race, marks)}"


def _day(value: date) -> str:
    # Noon UTC keeps the date the same on every reader's clock
    return f"<t:{int(datetime.combine(value, time(12), UTC).timestamp())}:d>"


def round_line(season_id: int, playday: int) -> str:
    """Round N and its dates, one date for a one-day round."""
    with Session() as session:
        row = session.get(DBSeasonRound, (season_id, playday))
    if row is None or row.start_date is None:
        return f"Round {playday}"
    dates = _day(row.start_date)
    if row.end_date and row.end_date != row.start_date:
        dates += f" to {_day(row.end_date)}"
    return f"Round {playday}: {dates}"


def header(series: SeriesPublic) -> list[str]:
    """The event, then the round: the card's two top lines."""
    match = series.match
    if match is None or match.season is None or match.season.id is None:
        return []
    if match.playday is None:
        return [f"## {md(match.season.name or '?')}"]
    return [
        f"## {md(match.season.name or '?')}",
        round_line(match.season.id, match.playday),
    ]


def teams(series: SeriesPublic) -> str:
    match = series.match
    if match is None or match.team1 is None or match.team2 is None:
        return ""
    return f"### {md(team_name(match.team1))} vs {md(team_name(match.team2))}"


def when(series: SeriesPublic) -> str:
    if series.date_time is None:
        return "Not scheduled yet"
    stamp = int(series.date_time.timestamp())
    return f"<t:{stamp}:F> · <t:{stamp}:R>"


def veto_lines(series: SeriesPublic) -> list[str]:
    """The games as the season's map rules play them, as the website's board
    words them, then each player's picks where a loser picks, whose turn it is,
    and the link to the board."""
    board = SeriesVetoService().board(series.id, None)
    names = {"A": _name(series.player1), "B": _name(series.player2)}
    rules = [
        rule.strip()
        for rule in (board.map_rules or DEFAULT_RULES).split(",")
        if rule.strip()
    ]
    picked = [step for step in board.steps if step.action.lower() == "pick"]
    used = {step.map_id for step in board.steps} | {board.week_map_id}
    with Session() as session:
        fixed = session.get(Map, board.week_map_id) if board.week_map_id else None
        rest = [session.get(Map, map_id) for map_id in board.pool if map_id not in used]
    left_over = iter([row.name for row in rest if row] if board.complete else [])
    picks = iter(picked)
    lines = []
    for number, rule in enumerate(rules, 1):
        if rule == "fixed":
            text = f"{md(fixed.name or '?')}, fixed map" if fixed else "fixed map"
        elif rule == "loser":
            text = f"loser of game {number - 1} picks" if number > 1 else "loser picks"
        elif rule == "veto":
            step = next(picks, None)
            left = None if step else next(left_over, None)
            if step:
                text = f"{md(step.name or '?')}, {names[step.side]}'s pick"
            else:
                text = f"{md(left)}, left over" if left else "not decided"
        else:
            text = "host picks"
        lines.append(f"Game {number} · {text}")
    if "loser" in rules and any(
        entry.lower().startswith("pick") for entry in board.order
    ):
        chosen = {step.side: md(step.name or "?") for step in picked}
        each = [
            f"{names[side]}: {chosen.get(side, 'not picked yet')}"
            for side in ("A", "B")
        ]
        lines.append("Picks · " + " · ".join(each))
    if not board.complete and len(board.steps) < len(board.order):
        action, _, side = board.order[len(board.steps)].partition("_")
        turn = f"{names[side.upper()]} to {action.lower()}"
        lines.append(f"Veto {len(board.steps)}/{len(board.order)}, {turn}")
    link = board_link(series.id)
    if link.startswith("http"):
        lines.append(f"[Veto board](<{link}>)")
    return lines


def cast_lines(series: SeriesPublic, names: bool = True) -> list[str]:
    return [
        f"- {cast_link(cast.channel_url)}" + (f" · {md(cast.name)}" if names else "")
        for cast in series.casts
    ]


def footed(embed: dict[str, Any], marks: Ratings) -> dict[str, Any]:
    """The footer: the W3C logo and when the MMR was synced. The time is the
    embed's timestamp, which Discord shows on each reader's clock and never goes
    stale; a written "3 hours ago" would, on a card that lives for days."""
    footer: dict[str, str] = {
        "text": "MMR synced" if marks.synced else "MMR not synced yet"
    }
    emojis = discord.app_emojis(os.getenv("DISCORD_APPLICATION_ID", ""))
    if "w3c" in emojis:
        footer["icon_url"] = discord.emoji_url(emojis["w3c"])
    card = {**embed, "footer": footer}
    if marks.synced:
        card["timestamp"] = marks.synced.isoformat()
    return card


def _embed(lines: list[str], marks: Ratings) -> dict[str, Any]:
    text = "\n".join(line for line in lines if line is not None)
    return footed({"description": text.strip(), "color": COLOR}, marks)


def match_lines(series: SeriesPublic, marks: Ratings) -> list[str]:
    """The series info, then the veto, then the casts."""
    lines = [*header(series), "", teams(series), players(series, marks), when(series)]
    lines += ["", "**Veto**", *veto_lines(series)]
    if series.casts:
        lines += ["", "**Casts**", *cast_lines(series)]
    return lines


def match_embed(series: SeriesPublic) -> dict[str, Any]:
    marks = ratings([series])
    return _embed(match_lines(series, marks), marks)


def claim_card(series: SeriesPublic) -> dict[str, Any]:
    """The card a claim posts: the match card and what the players do about the
    cast. It tags nobody: nothing on it asks for an answer now."""
    marks = ratings([series])
    lines = match_lines(series, marks)
    if series.casts:
        lines += [
            "",
            "Players: message each caster before the start and share the game name.",
        ]
    # An empty content clears the tags an older claim card carried when it is edited
    return {"content": "", "embeds": [_embed(lines, marks)]}


def _and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def reminder_card(series: SeriesPublic) -> dict[str, Any]:
    """The call before the start. The message tags the players and, when the
    series has casters, tells them to wait for the casters, tagging those too:
    a mention inside an embed notifies nobody."""
    marks = ratings([series])
    stamp = int(series.date_time.timestamp()) if series.date_time else None
    start = f"<t:{stamp}:R>" if stamp else "soon"
    content = (
        f"{ping(series.player1)} {ping(series.player2)}, your game starts {start}."
    )
    casters = [
        f"<@{cast.discord_id}>" if cast.discord_id else md(cast.name)
        for cast in series.casts
    ]
    if casters:
        content += f" Wait for your casters, {_and(casters)}, before you start."
    lines = [*header(series), "", teams(series), players(series, marks)]
    lines.append(f"Starts <t:{stamp}:R> (<t:{stamp}:t>)" if stamp else "Starts soon")
    if series.casts:
        lines += ["", "**Casts**", *cast_lines(series)]
    return {"content": content, "embeds": [_embed(lines, marks)]}


def _series_block(
    series: SeriesPublic, marks: Ratings, live: Callable[[SeriesPublic], bool]
) -> list[str]:
    dot = "🔴 " if live(series) else ""
    lines = [players(series, marks), f"{dot}{when(series)}"]
    return lines + (cast_lines(series, names=False) or ["No caster yet"])


def upcoming(
    rows: Sequence[SeriesPublic], live: Callable[[SeriesPublic], bool]
) -> dict[str, Any]:
    """One embed per round. In it the team matches, the one with a claimed
    series first, and in each match its claimed series first, then by time.
    What does not fit Discord's limits is counted on the last line. `live`
    says which series is on stream now."""
    marks = ratings(rows)
    far = datetime.max.replace(tzinfo=UTC)

    def at(series: SeriesPublic) -> datetime:
        return series.date_time or far

    def playday(series: SeriesPublic) -> int:
        return (series.match.playday if series.match else None) or 0

    by_round: dict[int, dict[int, list[SeriesPublic]]] = {}
    for series in sorted(rows, key=lambda s: (playday(s), at(s))):
        match_id = (series.match.id if series.match else None) or 0
        by_round.setdefault(playday(series), {}).setdefault(match_id, []).append(series)

    embeds: list[list[str]] = []
    total, shown, full = 0, 0, False
    for matches in by_round.values():
        groups = sorted(
            matches.values(),
            key=lambda group: (
                not any(s.casts for s in group),
                min(at(s) for s in group),
            ),
        )
        lines = header(groups[0][0])
        for group in groups:
            block = ["", teams(group[0])]
            for series in sorted(group, key=lambda s: (not s.casts, at(s))):
                block += _series_block(series, marks, live) + [""]
            size = len("\n".join(block))
            if total + size > BUDGET or len("\n".join(lines)) + size > DESCRIPTION:
                full = True
                break
            lines += block
            total += size
            shown += len(group)
        embeds.append(lines)
        # Discord takes ten embeds a message
        if full or len(embeds) == 10:
            break
    rest = len(rows) - shown
    if rest:
        site = (os.getenv("FRONTEND_URL") or "").rstrip("/")
        where = f" on the website: {site}/upcoming" if site else ""
        embeds[-1].append(f"And {rest} more series{where}")
    cards = [
        {"description": "\n".join(lines).strip(), "color": COLOR} for lines in embeds
    ]
    cards[-1] = footed(cards[-1], marks)
    return {"embeds": cards}
