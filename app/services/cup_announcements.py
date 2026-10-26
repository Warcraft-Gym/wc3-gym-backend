"""A cup's announcements in Discord: it opens, it starts soon, it is drawn, a
series is set, it is over.

The news of a cup goes to the channel the `announcement_channel_id` setting
names and pings the role `announcement_role_id` names: it opens, it starts soon,
it is over. A member joins or leaves that role on Home or at a cup sign-up, and
an `announcement_subscriber` row keeps the choice. A draw and every series set
after it go to the cup's own thread in that channel, under its sign-up
announcement, so the channel keeps the news alone. They ping the players of
those series instead, a team's captain for a team, with each series' host, a
link to its veto and its game name. A missing channel posts nothing, and a
missing role posts the news without a ping.

Each message is one discord_post row of its own kind about its subject, the
cup, a round of a cup played over rounds, a stage or a round of a stage. The
row is what makes it go out once: a job that runs every few minutes, a
redraw, a second publish or a second close posts nothing twice. Only a cup
announces; GNL seasons, KOTH nights and sign-up lists post nothing here. A
deleted cup drops its rows, and its messages stay in the channel.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, delete, event, exists, func, or_, select
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import load_only
from sqlmodel import col

from app.core import brackets
from app.core.battle_tags import has_login
from app.core.checkin_hint import checkin_window
from app.core.config import frontend_url
from app.core.db import Session, rel
from app.core.exceptions import ApiError, BadRequestError
from app.core.outcome import scored, won_slot
from app.models.announcement import AnnouncementState, AnnouncementSubscriber
from app.models.base import ident
from app.models.cup_rounds import CupLeg, CupLegStage
from app.models.cup_series import CupSeries, CupSeriesSide, game_name
from app.models.cup_team import CupTeam, CupTeamMember
from app.models.discord_post import DiscordPost
from app.models.enums import EntrantKind, EventKind, StageFormat
from app.models.event_award import EventAward
from app.models.event_division import EventDivision
from app.models.event_entrant import EventEntrant
from app.models.event_stage import EventStage
from app.models.map import Map
from app.models.relationships import DBEventRound
from app.models.season import NO_SERIES, Season, series_counts_by_event
from app.models.settings import Settings
from app.models.types import utcnow
from app.models.user import User
from app.services import cup_engine, cup_rounds, discord, event_cards, series_cards
from app.services.commands.base import md
from app.services.discord_posts import EVENT, remember, wait_for_channel
from app.services.events import EventService

logger = logging.getLogger(__name__)

# The settings that name where the announcements go and whom they ping
CHANNEL_KEY, ROLE_KEY = "announcement_channel_id", "announcement_role_id"
# The kinds of post, each about its own subject: the cup, a round of a cup
# played over rounds, a stage's first draw, one more round of a stage
OPEN, REMIND, LEG_REMIND = "cup_open", "cup_remind", "cup_leg_remind"
DRAW, ROUND, RESULT = "cup_draw", "cup_round", "cup_result"
# One later series, once both its sides stand
SERIES = "cup_series"
# The cup's thread, kept as the first message in it, and the message in the
# channel it hangs under when the cup has no sign-up announcement to hang under
THREAD, ANCHOR = "cup_thread", "cup_anchor"
# What one message holds: the accounts it pings, the width of a mention in the
# content, the content and the embed, inside Discord's 100, 2000 and 4096
MAX_PINGS, MENTION_WIDTH, MAX_CONTENT, MAX_EMBED = 100, 23, 1800, 4000
# How long before its check-in closes, or it starts, a cup or a round is called to check in
LEAD = timedelta(hours=1)
# The event columns the call reads
_CALL_COLUMNS = load_only(
    rel(Season.name),
    rel(Season.starts_at),
    rel(Season.checkin_enabled),
    rel(Season.checkin_opens_minutes),
    rel(Season.checkin_closes_minutes),
    rel(Season.checkin_closed_at),
    rel(Season.closed_at),
    rel(Season.cancelled_at),
    raiseload=True,
)
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}
NOT_SET_UP = "Announcements are not set up"
NO_ROLE = "Discord did not take the role; try again in a moment"
GUILD_ONLY = "Join the guild to take the announcements"
# What a member chose about the announcements; no row is no choice yet
SUBSCRIBED, DECLINED = "subscribed", "declined"


def _settings() -> tuple[str | None, str | None]:
    """The announcement channel and role, each None while its setting is missing."""
    with Session() as session:
        found = {
            row.key: row.value
            for row in session.scalars(
                select(Settings).where(col(Settings.key).in_((CHANNEL_KEY, ROLE_KEY)))
            )
        }
    return found.get(CHANNEL_KEY) or None, found.get(ROLE_KEY) or None


def _post_of(kind: str, subject_id: int) -> DiscordPost | None:
    with Session() as session:
        return session.scalars(
            select(DiscordPost)
            .where(
                col(DiscordPost.kind) == kind,
                col(DiscordPost.subject_id) == subject_id,
            )
            .limit(1)
        ).first()


def _link(event_id: int, label: str, tab: str | None = None) -> list[dict[str, Any]]:
    """One link button to the cup's page, or none while the site has no address."""
    site = frontend_url()
    if not site:
        return []
    url = f"{site}/events/{event_id}" + (f"?tab={tab}" if tab else "")
    return [
        {"type": 1, "components": [{"type": 2, "style": 5, "label": label, "url": url}]}
    ]


def _message(
    role: str | None,
    text: str,
    embeds: list[dict[str, Any]] | None = None,
    components: list[dict[str, Any]] | None = None,
    pings: Sequence[str] = (),
) -> dict[str, Any]:
    """The role's ping ahead of the text, allowed for that role and the accounts
    the text names alone; a mention inside an embed notifies nobody, so every
    ping rides in the content."""
    allowed: dict[str, Any] = {"roles": [role]} if role else {}
    if pings:
        allowed["users"] = list(pings)
    return {
        "content": f"<@&{role}> {text}" if role else text,
        "allowed_mentions": allowed or {"parse": []},
        "embeds": embeds or [],
        "components": components or [],
    }


def _send(
    kind: str,
    subject_id: int,
    text: str,
    embeds: list[dict[str, Any]] | None = None,
    components: list[dict[str, Any]] | None = None,
    pings: Sequence[str] = (),
) -> bool:
    """Post one announcement once; False when it was posted before, the channel
    is not set, or Discord did not take it."""
    if _post_of(kind, subject_id) is not None:
        return False
    channel, role = _settings()
    if not channel:
        return False
    wait_for_channel(channel)
    message_id = discord.post_to_channel(
        channel, _message(role, text, embeds, components, pings)
    )
    if not message_id:
        return False
    remember(kind, subject_id, channel, message_id)
    return True


def _cup(session: OrmSession, event_id: int) -> Season | None:
    """The cup while it may announce: published and not called off."""
    cup = session.get(Season, event_id)
    if (
        cup is None
        or cup.kind is not EventKind.cup
        or not cup.published
        or cup.cancelled_at is not None
    ):
        return None
    return cup


# ============ A new cup ============
def announce_open(event_id: int) -> bool:
    """Announce a cup the first time it reads published with its signups open."""
    with Session() as session:
        cup = _cup(session, event_id)
        if cup is None or not cup.signups_open or cup.closed_at is not None:
            return False
        name = cup.name
    if _post_of(OPEN, event_id) is not None:
        return False
    card = event_cards.card_embed(EventService().get(event_id))
    return _send(
        OPEN,
        event_id,
        f"A new cup takes signups: **{md(name or 'Cup')}**",
        [card],
        _link(event_id, "Sign up"),
    )


# ============ It starts soon ============
def _call_at(
    cup: Season, leg: CupLeg | None
) -> tuple[datetime, datetime | None] | None:
    """When the call of a cup, or of one round of it, goes, and when its
    check-in closes; None without a start.

    It goes an hour before the check-in closes early, else an hour before the
    start, or when the check-in opens if that is later. A cup that takes no
    check-in is called an hour before it starts.
    """
    start = leg.starts_at if leg is not None else cup.starts_at
    if start is None:
        return None
    if leg is None and not cup.checkin_enabled:
        return start - LEAD, None
    opens, closes = checkin_window(cup, leg)
    call = (closes or start) - LEAD
    if opens is not None:
        call = max(call, opens)
    return call, closes


def _due(cup: Season, leg: CupLeg | None, now: datetime) -> bool:
    """Whether the call is due at `now`: past its time, while the check-in stands open."""
    at = _call_at(cup, leg)
    if at is None:
        return False
    call, closes = at
    return call <= now and (closes is None or now < closes)


def _open_cup() -> tuple:
    return (
        col(Season.kind) == EventKind.cup,
        col(Season.published).is_(True),
        col(Season.closed_at).is_(None),
        col(Season.cancelled_at).is_(None),
    )


def _ceiling(session: OrmSession, until: datetime) -> datetime:
    """The latest start whose call falls by `until`: LEAD plus the largest early close."""
    closes = select(func.max(col(Season.checkin_closes_minutes))).where(*_open_cup())
    return until + LEAD + timedelta(minutes=session.scalar(closes) or 0)


def next_call(now: datetime, until: datetime) -> datetime | None:
    """The soonest call still to come after `now`, up to `until`. A call already
    due is left to remind_due, which runs first."""
    with Session() as session:
        ceiling = _ceiling(session, until)
        cups = session.scalars(
            select(Season)
            .options(_CALL_COLUMNS)
            .where(
                *_open_cup(),
                col(Season.starts_at) > now,
                col(Season.starts_at) <= ceiling,
                ~exists().where(col(CupLeg.event_id) == col(Season.id)),
            )
        )
        calls = [_call_at(cup, None) for cup in cups]
        legs = session.execute(
            select(CupLeg, Season)
            .options(_CALL_COLUMNS)
            .join(Season, col(Season.id) == col(CupLeg.event_id))
            .where(
                *_open_cup(),
                col(CupLeg.finished_at).is_(None),
                col(CupLeg.starts_at) > now,
                col(CupLeg.starts_at) <= ceiling,
            )
        ).tuples()
        calls += [_call_at(cup, leg) for leg, cup in legs]
    ahead = [at[0] for at in calls if at is not None and now < at[0] <= until]
    return min(ahead, default=None)


def remind_due(now: datetime) -> int:
    """Call every cup, and every round of a cup played over rounds, to check
    in, each once, at the time `_due` names: before it starts, and before its
    draw where it takes check-in.

    A cup played over rounds is called round by round, since each round takes
    its own check-in.
    """
    open_cup = _open_cup()
    with Session() as session:
        # a call falls at most LEAD plus the largest early close before the start
        ceiling = _ceiling(session, now)
        due = [
            cup
            for cup in session.scalars(
                select(Season)
                .options(_CALL_COLUMNS)
                .where(
                    *open_cup,
                    col(Season.starts_at) > now,
                    col(Season.starts_at) <= ceiling,
                    ~exists().where(col(CupLeg.event_id) == col(Season.id)),
                )
            )
            if _due(cup, None, now)
        ]
        drawn = series_counts_by_event(session, [cup.id for cup in due])
        cups = [
            (ident(cup), cup.name, start, cup.checkin_enabled)
            for cup in due
            if (start := cup.starts_at) is not None
            and not (cup.checkin_enabled and drawn.get(cup.id, NO_SERIES)[0])
        ]
        legs = [
            (ident(leg), leg.event_id, leg.number, leg.name, start, cup.name)
            for leg, cup in session.execute(
                select(CupLeg, Season)
                .options(_CALL_COLUMNS)
                .join(Season, col(Season.id) == col(CupLeg.event_id))
                .where(
                    *open_cup,
                    col(CupLeg.finished_at).is_(None),
                    col(CupLeg.starts_at) > now,
                    col(CupLeg.starts_at) <= ceiling,
                )
            ).tuples()
            if (start := leg.starts_at) is not None
            and _due(cup, leg, now)
            and not cup_rounds.leg_drawn(session, ident(leg))
        ]
    posted = 0
    for cup_id, name, starts_at, checkin in cups:
        check = " Check in now on the cup page." if checkin else ""
        text = (
            f"**{md(name or 'Cup')}** starts <t:{int(starts_at.timestamp())}:R>.{check}"
        )
        posted += _send(REMIND, cup_id, text, components=_link(cup_id, "Open the cup"))
    for leg_id, cup_id, number, leg_name, starts_at, name in legs:
        title = md(leg_name or f"Round {number}")
        text = (
            f"{title} of **{md(name or 'Cup')}** starts "
            f"<t:{int(starts_at.timestamp())}:R>. Check in for it on the cup page: "
            "the draw takes the players checked in."
        )
        posted += _send(LEG_REMIND, leg_id, text, components=_link(cup_id, "Check in"))
    return posted


# ============ It is drawn, and each series after ============
@dataclass(frozen=True)
class _Side:
    """One side as a message names it: the player or the team, and the Discord
    account it pings, the player's own or a team's captain's."""

    name: str
    ping: str | None


@dataclass(frozen=True)
class _Line:
    """One series as a message lists it, and the accounts it pings."""

    text: str
    pings: tuple[str, ...]
    # a bye names its one side and is no series to call
    bye: bool = False


def _sides(session: OrmSession, entrant_ids: set[int]) -> dict[int, _Side]:
    """Every entrant named, in two reads: the players, and the captains of the
    teams. A side with no Discord login is named and pings nobody."""
    if not entrant_ids:
        return {}
    found: dict[int, _Side] = {}
    teams: dict[int, tuple[int, str]] = {}
    for entrant_id, name, discord_id, team_id, team_name in session.execute(
        select(
            col(EventEntrant.id),
            col(User.name),
            col(User.discordId),
            col(CupTeam.id),
            col(CupTeam.name),
        )
        .outerjoin(User, col(User.id) == col(EventEntrant.user_id))
        .outerjoin(CupTeam, col(CupTeam.id) == col(EventEntrant.cup_team_id))
        .where(col(EventEntrant.id).in_(entrant_ids))
    ):
        if team_id is not None:
            teams[team_id] = (entrant_id, team_name or "A team")
        else:
            found[entrant_id] = _Side(
                md(name or "A player"), discord_id if has_login(discord_id) else None
            )
    # a team cup pings the captains, who pass the word on
    captains: dict[int, str | None] = (
        {
            team_id: discord_id
            for team_id, discord_id in session.execute(
                select(col(CupTeamMember.team_id), col(User.discordId))
                .join(User, col(User.id) == col(CupTeamMember.user_id))
                .where(
                    col(CupTeamMember.team_id).in_(list(teams)),
                    col(CupTeamMember.captain),
                )
            )
        }
        if teams
        else {}
    )
    for team_id, (entrant_id, team_name) in teams.items():
        captain = captains.get(team_id)
        found[entrant_id] = _Side(
            md(team_name), captain if has_login(captain) else None
        )
    return found


def _link_to(site: str | None, event_id: int, series_id: int | None) -> str | None:
    """The cup's draw, with one series' veto open when it names one."""
    if not site:
        return None
    return f"{site}/events/{event_id}?tab=draw" + (
        f"&veto={series_id}" if series_id is not None else ""
    )


def _lines(session: OrmSession, cup: Season, rows: Sequence[CupSeries]) -> list[_Line]:
    """The series of a message, each a line: who plays whom with the host
    marked, a link to its veto, and last its game name, in code style so the
    underscore stays plain text. A bye is named and pings nobody; a series still
    waiting for a side, and one played, are left out. The host is side 2, the
    bottom row of the box, and the last seat of a lobby."""
    from app.services.cup_divisions import custom_game

    seats: dict[int, list[CupSeriesSide]] = {}
    for seat in session.scalars(
        select(CupSeriesSide)
        .where(col(CupSeriesSide.series_id).in_([ident(row) for row in rows]))
        .order_by(col(CupSeriesSide.series_id), col(CupSeriesSide.side_no))
    ):
        seats.setdefault(seat.series_id, []).append(seat)
    entrants = {
        entrant_id
        for row in rows
        for entrant_id in (
            row.entrant1_id,
            row.entrant2_id,
            *(seat.entrant_id for seat in seats.get(ident(row), [])),
        )
        if entrant_id is not None
    }
    sides = _sides(session, entrants)
    maps: dict[int, str] = {
        map_id: map_name
        for map_id, map_name in session.execute(
            select(col(Map.id), col(Map.name)).where(
                col(Map.id).in_(
                    [row.lobby_map_id for row in rows if row.lobby_map_id is not None]
                )
            )
        )
    }
    vetoes = not custom_game(session, cup)
    site = frontend_url()
    lines: list[_Line] = []
    for row in rows:
        series_id = ident(row)
        lobby = seats.get(series_id, [])
        if len({seat.side_no for seat in lobby}) > 2:
            if any(seat.entrant_id is None for seat in lobby) or scored(row):
                continue
            named = [
                sides[seat.entrant_id] for seat in lobby if seat.entrant_id in sides
            ]
            if not named:
                continue
            names = [side.name for side in named[:-1]] + [
                f"**{named[-1].name}** (hosts)"
            ]
            where = (
                f" · {md(maps[row.lobby_map_id])}" if row.lobby_map_id in maps else ""
            )
            link = _link_to(site, ident(cup), None)
            lines.append(
                _Line(
                    f"{', '.join(names)}{where}"
                    + (f" · [Open]({link})" if link else "")
                    + _game(series_id),
                    tuple(side.ping for side in named if side.ping),
                )
            )
            continue
        first = sides.get(row.entrant1_id) if row.entrant1_id is not None else None
        second = sides.get(row.entrant2_id) if row.entrant2_id is not None else None
        if (first is None) != (second is None) and row.result_kind == "walkover":
            alone = first or second
            if alone is not None:
                lines.append(_Line(f"**{alone.name}** · bye", (), bye=True))
            continue
        if first is None or second is None or scored(row):
            continue
        link = _link_to(site, ident(cup), series_id if vetoes else None)
        label = "Veto" if vetoes else "Open"
        lines.append(
            _Line(
                f"**{first.name}** vs **{second.name}** (hosts)"
                + (f" · [{label}]({link})" if link else "")
                + _game(series_id),
                tuple(side.ping for side in (first, second) if side.ping),
            )
        )
    return lines


def _game(series_id: int) -> str:
    """The end of a series' line: the name its game is hosted under."""
    return f" · Game Name: `{game_name(series_id)}`"


def _ping_message(
    text: str,
    pings: Sequence[str],
    lines: Sequence[str],
    components: list[dict[str, Any]],
) -> dict[str, Any]:
    """The text and the pings of the players in the content, where a mention
    notifies, allowed for those accounts alone; the series in an embed."""
    return {
        "content": f"{text}\n{' '.join(f'<@{ping}>' for ping in pings)}"
        if pings
        else text,
        "allowed_mentions": {"users": list(pings)} if pings else {"parse": []},
        "embeds": (
            [{"description": "\n".join(lines), "color": series_cards.COLOR}]
            if lines
            else []
        ),
        "components": components,
    }


def _chunks(lines: Sequence[_Line]) -> list[list[_Line]]:
    """The lines split over as many messages as Discord's limits need: the
    pings of a message in its content, at most 100 accounts, and its series in
    one embed. Every ping and every line goes out."""
    chunks: list[list[_Line]] = [[]]
    pings = length = 0
    for line in lines:
        mentions = len(line.pings)
        if chunks[-1] and (
            pings + mentions > MAX_PINGS
            or (pings + mentions) * MENTION_WIDTH > MAX_CONTENT
            or length + len(line.text) + 1 > MAX_EMBED
        ):
            chunks.append([])
            pings = length = 0
        chunks[-1].append(line)
        pings += mentions
        length += len(line.text) + 1
    return chunks


def _quiet(text: str) -> dict[str, Any]:
    """A message that pings nobody."""
    return {"content": text, "allowed_mentions": {"parse": []}}


def _thread(event_id: int, name: str, channel: str) -> str:
    """Where the cup's draw and series go: its thread, opened once under its
    sign-up announcement, or under a short message of its own when it has
    none. The thread opens with a message that says what it holds, which is
    the row that keeps it. The channel itself when no thread opens, so no
    draw is lost."""
    kept = _post_of(THREAD, event_id)
    if kept is not None:
        return kept.channel_id
    title = f"**{md(name)}**"
    anchor = _post_of(OPEN, event_id) or _post_of(ANCHOR, event_id)
    if anchor is not None:
        parent, message_id = anchor.channel_id, anchor.message_id
    else:
        wait_for_channel(channel)
        message_id = discord.post_to_channel(
            channel, _quiet(f"{title}: its draw and every series follow in its thread.")
        )
        if not message_id:
            return channel
        remember(ANCHOR, event_id, channel, message_id)
        parent = channel
    # A thread opened before whose first message did not go out has the
    # anchor's id, so a refused second start still finds it
    thread = discord.start_thread(parent, message_id, name) or message_id
    first = discord.post_to_channel(
        thread, _quiet(f"The draw and every series of {title} go here.")
    )
    if not first:
        logger.warning("Cup %s has no thread; its draw goes to the channel", event_id)
        return channel
    remember(THREAD, event_id, thread, first)
    return thread


def _send_lines(
    kind: str,
    subject_id: int,
    cup: tuple[int, str],
    text: str,
    lines: Sequence[_Line],
    components: list[dict[str, Any]],
) -> bool:
    """Post the series of a draw or of one later series once in the cup's
    thread, pinging their players and not the role; a long draw goes out in
    several messages, each kept against the same subject. A mention in a
    thread adds the player to it."""
    if _post_of(kind, subject_id) is not None:
        return False
    channel, _ = _settings()
    if not channel:
        return False
    channel = _thread(*cup, channel)
    sent = False
    for index, chunk in enumerate(_chunks(lines) if lines else [[]]):
        pings = list(dict.fromkeys(ping for line in chunk for ping in line.pings))
        wait_for_channel(channel)
        message_id = discord.post_to_channel(
            channel,
            _ping_message(
                text if index == 0 else f"{text} (continued)",
                pings,
                [line.text for line in chunk],
                components,
            ),
        )
        if not message_id:
            return sent
        remember(kind, subject_id, channel, message_id)
        sent = True
    return sent


def _drawn_rows(
    session: OrmSession, stage_id: int, round_id: int | None
) -> list[CupSeries]:
    """The series a draw made: every series of the stage, or of its new round,
    in play order."""
    query = select(CupSeries).join(
        DBEventRound, col(DBEventRound.id) == col(CupSeries.round_id)
    )
    query = (
        query.where(col(CupSeries.round_id) == round_id)
        if round_id is not None
        else query.where(col(DBEventRound.stage_id) == stage_id)
    )
    return list(
        session.scalars(
            query.order_by(
                col(DBEventRound.number), col(CupSeries.sequence), col(CupSeries.id)
            )
        )
    )


def post_draw(
    event_id: int, stage_id: int, round_id: int | None, round_name: str | None
) -> bool:
    """Say a stage is drawn, or one more of its rounds, with every series it
    set: who plays whom, the game name, the host and a link to each veto. It
    pings the players of those series, not the role. A redraw of a stage
    already announced posts nothing."""
    kind, subject = (DRAW, stage_id) if round_id is None else (ROUND, round_id)
    if _post_of(kind, subject) is not None:
        return False
    with Session() as session:
        cup = _cup(session, event_id)
        stage = session.get(EventStage, stage_id)
        if cup is None or stage is None:
            return False
        leg = session.scalars(
            select(CupLeg)
            .join(CupLegStage, col(CupLegStage.leg_id) == col(CupLeg.id))
            .where(col(CupLegStage.stage_id) == stage_id)
        ).first()
        title = cup.name or "Cup"
        name = f"**{md(title)}**"
        # A cup over rounds names the round; a later stage names itself
        where = (
            md(leg.name or f"Round {leg.number}")
            if leg is not None
            else md(stage.name or f"Stage {stage.position}")
            if stage.position > 1
            else None
        )
        lines = _lines(session, cup, _drawn_rows(session, stage_id, round_id))
    if round_id is not None:
        part = md(round_name or "A new round")
        text = f"{part}{f' of {where}' if where else ''} of {name} is drawn."
    elif where:
        text = f"{where} of {name} is drawn."
    else:
        text = f"The draw of {name} is out."
    return _send_lines(
        kind,
        subject,
        (event_id, title),
        text,
        lines,
        _link(event_id, "See the draw", "draw"),
    )


def post_series(series_id: int, drawn: set[int] | None = None) -> bool:
    """Say one later series is set once both its sides stand, or every seat of
    a lobby, the way the draw names its series. A series of a stage drawn in the
    same write is in the draw's message already, and each goes out once."""
    if _post_of(SERIES, series_id) is not None:
        return False
    with Session() as session:
        row = session.get(CupSeries, series_id)
        round_row = session.get(DBEventRound, row.round_id) if row is not None else None
        if row is None or round_row is None:
            return False
        if drawn and round_row.stage_id in drawn:
            return False
        cup = _cup(session, round_row.season_id)
        if cup is None or cup.closed_at is not None:
            return False
        lines = _lines(session, cup, [row])
        text = (
            f"**{md(round_row.name or f'Round {round_row.number}')}** of "
            f"**{md(cup.name or 'Cup')}** is set."
        )
        about = (ident(cup), cup.name or "Cup")
    # a bye, a played series or a side still missing is no series to call
    if not lines or lines[0].bye:
        return False
    return _send_lines(
        SERIES, series_id, about, text, lines, _link(about[0], "See the draw", "draw")
    )


def replace_series(series_id: int) -> None:
    """A series named before whose pairing a corrected result took back: its
    message says so, and its row goes, so the new pairing is named when it
    stands. An edit pings nobody, which is why the new pairing has a message of
    its own."""
    with Session() as session:
        posted = list(
            session.scalars(
                select(DiscordPost).where(
                    col(DiscordPost.kind) == SERIES,
                    col(DiscordPost.subject_id) == series_id,
                )
            )
        )
    for post in posted:
        wait_for_channel(post.channel_id)
        discord.edit_channel_message(
            post.channel_id,
            post.message_id,
            {
                "content": "A corrected result changed this pairing; the new one follows.",
                "allowed_mentions": {"parse": []},
                "embeds": [],
                "components": [],
            },
        )
    with Session.begin() as session:
        session.execute(
            delete(DiscordPost).where(
                col(DiscordPost.kind) == SERIES,
                col(DiscordPost.subject_id) == series_id,
            )
        )


@event.listens_for(Session, "after_commit")
def _announce_draws(session: OrmSession) -> None:
    """Post the draws the transaction made once it holds, then mark the series
    it emptied as replaced and name the ones it filled. A failure is logged and
    never reaches the write that drew or scored."""
    draws = list(dict.fromkeys(session.info.pop(cup_engine.DRAWS, [])))
    emptied = list(dict.fromkeys(session.info.pop(cup_engine.EMPTIED, [])))
    filled = list(dict.fromkeys(session.info.pop(cup_engine.FILLED, [])))
    for draw in draws:
        try:
            post_draw(*draw)
        except Exception:
            logger.exception("The draw announcement of event %s failed", draw[0])
    drawn = {draw[1] for draw in draws}
    for series_id in emptied:
        try:
            replace_series(series_id)
        except Exception:
            logger.exception("The replaced series %s was not marked", series_id)
    for series_id in filled:
        try:
            post_series(series_id, drawn)
        except Exception:
            logger.exception("The announcement of series %s failed", series_id)
    # a cup its last result or round closed posts its podium last
    for event_id in dict.fromkeys(session.info.pop(cup_engine.CLOSED, [])):
        try:
            announce_result(event_id)
        except Exception:
            logger.exception("The podium of event %s was not posted", event_id)


@event.listens_for(Session, "after_rollback")
def _forget_draws(session: OrmSession) -> None:
    for key in (
        cup_engine.DRAWS,
        cup_engine.EMPTIED,
        cup_engine.FILLED,
        cup_engine.CLOSED,
    ):
        session.info.pop(key, None)


# ============ It is over ============
@dataclass(frozen=True)
class _Podium:
    """What a closed cup's message says: a block of credit lines per division,
    unnamed on a cup without divisions, the podium it congratulates by name and
    the accounts that pings, and the cup's figures."""

    blocks: list[tuple[str | None, list[str]]]
    names: list[str]
    pings: tuple[str, ...]
    figures: str


# What each podium place is called in its credit line
PLACE_WORDS = {1: "champion", 2: "runner-up", 3: "third"}
THANKS = (
    "Thank you all for playing! We hope you had fun, and we'd love to see you "
    "at the next cup."
)
# The cards one Discord message carries
MAX_EMBEDS = 10
# The brackets whose champion wins a final against the runner-up
FINALS = (StageFormat.single_elimination, StageFormat.double_elimination)


def _count(number: int, word: str, plural: str | None = None) -> str:
    return f"{number} {word if number == 1 else plural or f'{word}s'}"


def _and(items: Sequence[str]) -> str:
    """The items as a sentence lists them: "A", "A and B", "A, B and C"."""
    return " and ".join([", ".join(items[:-1]), items[-1]] if len(items) > 1 else items)


def _scored_series(
    session: OrmSession, event_id: int
) -> list[tuple[CupSeries, DBEventRound, EventStage]]:
    """Every scored series of the cup, with its round and stage, in one read."""
    return [
        (row, round_row, stage)
        for row, round_row, stage in session.execute(
            select(CupSeries, DBEventRound, EventStage)
            .join(DBEventRound, col(DBEventRound.id) == col(CupSeries.round_id))
            .join(EventStage, col(EventStage.id) == col(DBEventRound.stage_id))
            .where(col(DBEventRound.season_id) == event_id)
        ).tuples()
        if scored(row)
    ]


def _paired(row: CupSeries, stage: EventStage) -> bool:
    """A series two sides played out: no lobby, and no bye a padded bracket gave."""
    return (
        stage.format is not StageFormat.ffa
        and row.entrant1_id is not None
        and row.entrant2_id is not None
    )


def _records(
    played: Sequence[tuple[CupSeries, DBEventRound, EventStage]],
) -> dict[int, tuple[int, int]]:
    """Each entrant's series won and lost over the cup's two-sided series."""
    records: dict[int, tuple[int, int]] = {}
    for row, _, stage in played:
        won = won_slot(row)
        if not _paired(row, stage) or won is None:
            continue
        for slot, entrant in ((1, row.entrant1_id), (2, row.entrant2_id)):
            wins, losses = records.get(entrant or 0, (0, 0))
            records[entrant or 0] = (
                (wins + 1, losses) if slot == won else (wins, losses + 1)
            )
    return records


def _final(
    played: Sequence[tuple[CupSeries, DBEventRound, EventStage]],
    champion: int,
    runner_up: int,
) -> tuple[int, int] | None:
    """The champion's score in the last bracket series it won against the
    runner-up, champion first: the final, with any head start in it."""
    meetings = [
        (stage.position, round_row.number or 0, ident(row), row)
        for row, round_row, stage in played
        if stage.format in FINALS
        and _paired(row, stage)
        and {row.entrant1_id, row.entrant2_id} == {champion, runner_up}
    ]
    if not meetings:
        return None
    *_, row = max(meetings, key=lambda meeting: meeting[:3])
    first = row.entrant1_id == champion
    if won_slot(row) != (1 if first else 2):
        return None
    scores = (row.player1_score or 0, row.player2_score or 0)
    return scores if first else (scores[1], scores[0])


def _figures(
    session: OrmSession,
    teams: bool,
    played: Sequence[tuple[CupSeries, DBEventRound, EventStage]],
    rounds: int,
) -> str:
    """The cup in numbers: who played, the rounds of a cup played over rounds,
    the series or lobbies, and the maps a cup of one evening played, a grand
    final's head start not counted."""
    paired = [
        (row, round_row, stage)
        for row, round_row, stage in played
        if _paired(row, stage)
    ]
    lobbies = [
        ident(row) for row, _, stage in played if stage.format is StageFormat.ffa
    ]
    entrants = {
        entrant
        for row, *_ in paired
        for entrant in (row.entrant1_id, row.entrant2_id)
        if entrant is not None
    }
    if lobbies:
        entrants |= {
            entrant
            for entrant in session.scalars(
                select(col(CupSeriesSide.entrant_id)).where(
                    col(CupSeriesSide.series_id).in_(lobbies)
                )
            )
            if entrant is not None
        }
    parts = [_count(len(entrants), "team" if teams else "player")]
    if rounds:
        parts.append(_count(rounds, "round"))
    if paired:
        parts.append(_count(len(paired), "series", "series"))
    if lobbies:
        parts.append(_count(len(lobbies), "lobby", "lobbies"))
    maps = sum(
        (row.player1_score or 0)
        + (row.player2_score or 0)
        - brackets.head_start(
            round_row.name, stage.grand_final_modifier, stage.grand_final_lead
        )
        for row, round_row, stage in paired
        if row.result_kind == "played"
    )
    if maps and not rounds:
        parts.append(_count(maps, "map"))
    return " · ".join(parts)


def _cards(
    name: str, blocks: Sequence[tuple[str | None, list[str]]], closing: list[str]
) -> list[dict[str, Any]]:
    """The podium message's cards: one holding everything on a cup of one
    block; else one per division and a closing card with the figures and the
    thank-you, which lists the divisions past Discord's ten cards."""

    def card(lines: Sequence[str]) -> dict[str, Any]:
        return {"description": "\n".join(lines), "color": series_cards.COLOR}

    if len(blocks) == 1:
        return [card([f"## 🏆 {name}", *blocks[0][1], "", *closing])]
    shown, rest = blocks[: MAX_EMBEDS - 1], blocks[MAX_EMBEDS - 1 :]
    cards = [
        card([f"## 🏆 {name}" + (f" · {label}" if label else ""), *lines])
        for label, lines in shown
    ]
    listed = [
        line
        for label, lines in rest
        for line in ([f"**{label}**"] if label else []) + [*lines, ""]
    ]
    return [*cards, card([*listed, *closing])]


def _podium(session: OrmSession, cup: Season) -> _Podium | None:
    """The podium of a closed cup: per division, each place's credit line with
    the series record and the champion's final, or the overall table's points
    for a cup played over rounds; who it congratulates; the cup's figures."""
    event_id = ident(cup)
    teams = cup.entrant_kind is EntrantKind.team
    played = _scored_series(session, event_id)
    if cup_rounds.has_legs(session, event_id):
        top = [
            row
            for row in cup_rounds.overall_rows(session, event_id)
            if row.legs and row.position in MEDALS
        ]
        lines = [
            f"{MEDALS[row.position]} **{md(row.name or 'Unknown')}**, "
            f"{PLACE_WORDS[row.position]}: {_count(row.points, 'pt')} from "
            f"{_count(len(row.legs), 'round')}"
            for row in top
        ]
        blocks: list[tuple[str | None, list[str]]] = [(None, lines)] if lines else []
        placed = [row.entrant_id for row in top]
        rounds = sum(
            leg.finished_at is not None for leg in cup_rounds.legs_of(session, event_id)
        )
    else:
        blocks, placed = _division_blocks(session, event_id, played)
        rounds = 0
    if not blocks:
        return None
    sides = _sides(session, set(placed))
    names: list[str] = []
    for entrant in dict.fromkeys(placed):
        side = sides.get(entrant)
        if side is None:
            continue
        mention = f"<@{side.ping}>" if side.ping else None
        if teams:
            names.append(f"**{side.name}**" + (f" ({mention})" if mention else ""))
        else:
            names.append(mention or f"**{side.name}**")
    pings = tuple(dict.fromkeys(side.ping for side in sides.values() if side.ping))
    return _Podium(blocks, names, pings, _figures(session, teams, played, rounds))


def _division_blocks(
    session: OrmSession,
    event_id: int,
    played: Sequence[tuple[CupSeries, DBEventRound, EventStage]],
) -> tuple[list[tuple[str | None, list[str]]], list[int]]:
    """The credit lines of a cup of one evening, per division, from the places
    its close paid, and the entrants they name, best place first."""
    found = session.execute(
        select(EventAward, EventEntrant, User, CupTeam, EventDivision)
        .join(EventEntrant, col(EventEntrant.id) == col(EventAward.entrant_id))
        .outerjoin(User, col(User.id) == col(EventEntrant.user_id))
        .outerjoin(CupTeam, col(CupTeam.id) == col(EventEntrant.cup_team_id))
        .outerjoin(
            EventDivision, col(EventDivision.id) == col(EventEntrant.division_id)
        )
        .where(col(EventAward.event_id) == event_id, col(EventAward.place) <= 3)
        .order_by(
            col(EventDivision.position), col(EventAward.place), col(EventAward.id)
        )
    ).all()
    team_ids = [ident(team) for *_, team, _ in found if team is not None]
    players: dict[int, list[str]] = {}
    for team_id, name in session.execute(
        select(col(CupTeamMember.team_id), col(User.name))
        .join(User, col(User.id) == col(CupTeamMember.user_id))
        .where(col(CupTeamMember.team_id).in_(team_ids))
        .order_by(col(CupTeamMember.captain).desc(), col(User.name))
    ):
        players.setdefault(team_id, []).append(md(name or ""))
    records = _records(played)
    divisions: dict[int | None, tuple[str | None, list[tuple[int, int, str, str]]]] = {}
    for award, _, user, team, band in found:
        plain = md(team.name if team else user.name if user else "Unknown")
        who = f"**{plain}**" + (
            f" ({', '.join(players.get(ident(team), []))})" if team else ""
        )
        label = md(band.name or f"Division {band.position}") if band else None
        divisions.setdefault(ident(band) if band else None, (label, []))[1].append(
            (award.place or 0, award.entrant_id or 0, who, plain)
        )
    blocks: list[tuple[str | None, list[str]]] = []
    for label, places in divisions.values():
        runner = next(
            ((entrant, plain) for place, entrant, _, plain in places if place == 2),
            None,
        )
        lines = []
        for place, entrant, who, _ in places:
            details = []
            if entrant in records:
                details.append("{}–{} in series".format(*records[entrant]))
            if place == 1 and runner and (final := _final(played, entrant, runner[0])):
                details.append(
                    f"won the final {final[0]}–{final[1]} against {runner[1]}"
                )
            line = f"{MEDALS.get(place, '')} {who}, {PLACE_WORDS.get(place, '')}"
            lines.append(line + (f": {', '.join(details)}" if details else ""))
        blocks.append((label, lines))
    return blocks, [award.entrant_id or 0 for award, *_ in found]


def announce_result(event_id: int) -> bool:
    """Post a closed cup's podium once: a card per division with each place's
    credit, the cup's figures and a thank-you, pinging the role and the podium.
    A close after a reopen edits that message, which pings nobody again."""
    with Session() as session:
        cup = _cup(session, event_id)
        if cup is None or cup.closed_at is None:
            return False
        name = md(cup.name or "Cup")
        podium = _podium(session, cup)
    if podium is None:
        return False
    text = f"🏆 **{name}** is over!" + (
        f"\nCongratulations {_and(podium.names)}!" if podium.names else ""
    )
    embeds = _cards(name, podium.blocks, [podium.figures, "", THANKS])
    links = _link(event_id, "Results", "results")
    posted = _post_of(RESULT, event_id)
    if posted is None:
        return _send(RESULT, event_id, text, embeds, links, podium.pings)
    _, role = _settings()
    wait_for_channel(posted.channel_id)
    discord.edit_channel_message(
        posted.channel_id,
        posted.message_id,
        _message(role, text, embeds, links, podium.pings),
    )
    with Session.begin() as session:
        row = session.get(DiscordPost, ident(posted))
        if row is not None:
            row.edited_at = utcnow()
    return True


# ============ It is deleted ============
def forget_cup(session: OrmSession, event_id: int) -> None:
    """Drop the rows of every post about a cup that is deleted, its event card
    too. The messages stay in the channel, and nothing edits them again."""

    def about(kind: str, ids: Any) -> Any:  # noqa: ANN401
        return and_(col(DiscordPost.kind) == kind, col(DiscordPost.subject_id).in_(ids))

    stages = select(col(EventStage.id)).where(col(EventStage.event_id) == event_id)
    rounds = select(col(DBEventRound.id)).where(col(DBEventRound.season_id) == event_id)
    legs = select(col(CupLeg.id)).where(col(CupLeg.event_id) == event_id)
    series = select(col(CupSeries.id)).where(col(CupSeries.round_id).in_(rounds))
    session.execute(
        delete(DiscordPost).where(
            or_(
                and_(
                    col(DiscordPost.kind).in_(
                        (OPEN, REMIND, RESULT, EVENT, THREAD, ANCHOR)
                    ),
                    col(DiscordPost.subject_id) == event_id,
                ),
                about(DRAW, stages),
                about(ROUND, rounds),
                about(LEG_REMIND, legs),
                about(SERIES, series),
            )
        )
    )


# ============ The Home switch ============
def _member_of(claims: dict[str, Any] | None) -> str | None:
    """The guild member's Discord account behind the session; None for a guest
    or the admin token, which hold no account to give a role."""
    if not claims or claims.get("role") == "guest" or claims.get("sub") == "admin":
        return None
    return str(claims["sub"])


def state_of(claims: dict[str, Any] | None) -> AnnouncementState:
    channel, role = _settings()
    member = _member_of(claims)
    if not (channel and role and member):
        return AnnouncementState(available=False, subscribed=False)
    with Session() as session:
        row = session.get(AnnouncementSubscriber, member)
    # a member who never chose is asked at the next cup sign-up
    return AnnouncementState(
        available=True,
        subscribed=row is not None and row.status == SUBSCRIBED,
        ask=row is None,
    )


def subscribe(claims: dict[str, Any] | None, subscribed: bool) -> AnnouncementState:
    """Take or leave the announcement role. The role is written first, so a
    refusal changes nothing and the switch says it did not go through. Leaving
    it, from Home or from the sign-up question, is a choice too: the row stays
    as declined, so no sign-up asks again."""
    channel, role = _settings()
    if not (channel and role):
        raise BadRequestError(NOT_SET_UP)
    member = _member_of(claims)
    if member is None:
        raise ApiError(403, {"error": GUILD_ONLY})
    if not discord.set_role(member, role, subscribed):
        raise ApiError(502, {"error": NO_ROLE})
    with Session.begin() as session:
        row = session.get(AnnouncementSubscriber, member)
        status = SUBSCRIBED if subscribed else DECLINED
        if row is None:
            session.add(AnnouncementSubscriber(discord_id=member, status=status))
        else:
            row.status = status
    return AnnouncementState(available=True, subscribed=subscribed)
