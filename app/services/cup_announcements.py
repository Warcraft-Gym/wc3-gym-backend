"""A cup's announcements in Discord: it opens, it starts soon, it is drawn, it is over.

Every message goes to the channel the `announcement_channel_id` setting names
and pings the role `announcement_role_id` names. A member joins or leaves that
role on Home, and an `announcement_subscriber` row keeps the choice. A missing
channel posts nothing, and a missing role posts without a ping.

Each message is one discord_post row of its own kind about its subject, the
cup, a round of a cup played over rounds, a stage or a round of a stage. The
row is what makes it go out once: a job that runs every few minutes, a
redraw, a second publish or a second close posts nothing twice. Only a cup
announces; GNL seasons, KOTH nights and sign-up lists post nothing here. A
deleted cup drops its rows, and its messages stay in the channel.
"""

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, delete, event, exists, func, or_, select
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import load_only
from sqlmodel import col

from app.core.checkin_hint import checkin_window
from app.core.config import frontend_url
from app.core.db import Session, rel
from app.core.exceptions import ApiError, BadRequestError
from app.models.announcement import AnnouncementState, AnnouncementSubscriber
from app.models.base import ident
from app.models.cup_rounds import CupLeg, CupLegStage
from app.models.cup_team import CupTeam, CupTeamMember
from app.models.discord_post import DiscordPost
from app.models.enums import EventKind
from app.models.event_award import EventAward
from app.models.event_division import EventDivision
from app.models.event_entrant import EventEntrant
from app.models.event_stage import EventStage
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
) -> dict[str, Any]:
    """The role's ping ahead of the text, allowed for that role alone; a mention
    inside an embed notifies nobody, so the ping rides in the content."""
    return {
        "content": f"<@&{role}> {text}" if role else text,
        "allowed_mentions": {"roles": [role]} if role else {"parse": []},
        "embeds": embeds or [],
        "components": components or [],
    }


def _send(
    kind: str,
    subject_id: int,
    text: str,
    embeds: list[dict[str, Any]] | None = None,
    components: list[dict[str, Any]] | None = None,
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
        channel, _message(role, text, embeds, components)
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
def _due(cup: Season, leg: CupLeg | None, now: datetime) -> bool:
    """Whether the call of a cup, or of one round of it, is due at `now`.

    It goes an hour before the check-in closes early, else an hour before the
    start, or when the check-in opens if that is later, and only while the
    check-in stands open. A cup that takes no check-in is called an hour
    before it starts.
    """
    start = leg.starts_at if leg is not None else cup.starts_at
    if start is None:
        return False
    if leg is None and not cup.checkin_enabled:
        return start - LEAD <= now
    opens, closes = checkin_window(cup, leg)
    call = (closes or start) - LEAD
    if opens is not None:
        call = max(call, opens)
    return call <= now and (closes is None or now < closes)


def remind_due(now: datetime) -> int:
    """Call every cup, and every round of a cup played over rounds, to check
    in, each once, at the time `_due` names: before it starts, and before its
    draw where it takes check-in.

    A cup played over rounds is called round by round, since each round takes
    its own check-in.
    """
    open_cup = (
        col(Season.kind) == EventKind.cup,
        col(Season.published).is_(True),
        col(Season.closed_at).is_(None),
        col(Season.cancelled_at).is_(None),
    )
    with Session() as session:
        # a call falls at most LEAD plus the largest early close before the start
        closes = select(func.max(col(Season.checkin_closes_minutes))).where(*open_cup)
        ceiling = now + LEAD + timedelta(minutes=session.scalar(closes) or 0)
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


# ============ It is drawn ============
def post_draw(
    event_id: int, stage_id: int, round_id: int | None, round_name: str | None
) -> bool:
    """Say a stage is drawn, or one more of its rounds; a redraw of a stage
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
        name = f"**{md(cup.name or 'Cup')}**"
        # A cup over rounds names the round; a later stage names itself
        where = (
            md(leg.name or f"Round {leg.number}")
            if leg is not None
            else md(stage.name or f"Stage {stage.position}")
            if stage.position > 1
            else None
        )
    if round_id is not None:
        part = md(round_name or "A new round")
        text = f"{part}{f' of {where}' if where else ''} of {name} is drawn."
    elif where:
        text = f"{where} of {name} is drawn."
    else:
        text = f"The draw of {name} is out."
    return _send(
        kind, subject, text, components=_link(event_id, "See the draw", "draw")
    )


@event.listens_for(Session, "after_commit")
def _announce_draws(session: OrmSession) -> None:
    """Post the draws the transaction made once it holds; a failure is logged
    and never reaches the write that drew."""
    for draw in dict.fromkeys(session.info.pop(cup_engine.DRAWS, [])):
        try:
            post_draw(*draw)
        except Exception:
            logger.exception("The draw announcement of event %s failed", draw[0])


@event.listens_for(Session, "after_rollback")
def _forget_draws(session: OrmSession) -> None:
    session.info.pop(cup_engine.DRAWS, None)


# ============ It is over ============
def _podium(session: OrmSession, event_id: int) -> list[str]:
    """The top three as card lines: per division, or the overall table with its
    points for a cup played over rounds."""
    if cup_rounds.has_legs(session, event_id):
        return [
            f"{MEDALS[row.position]} {md(row.name or 'Unknown')} · {row.points} pts"
            for row in cup_rounds.overall_rows(session, event_id)
            if row.legs and row.position in MEDALS
        ]
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
    lines: list[str] = []
    division: int | None = None
    for award, _, user, team, band in found:
        if band is not None and ident(band) != division:
            division = ident(band)
            lines.append(f"**{md(band.name or f'Division {band.position}')}**")
        if team is not None:
            who = f"{md(team.name)} ({', '.join(players.get(ident(team), []))})"
        else:
            who = md(user.name if user else "Unknown")
        lines.append(f"{MEDALS.get(award.place or 0, '')} {who}")
    return lines


def announce_result(event_id: int) -> bool:
    """Post a closed cup's top three once; a close after a reopen edits that
    card, which pings nobody again."""
    with Session() as session:
        cup = _cup(session, event_id)
        if cup is None or cup.closed_at is None:
            return False
        name = md(cup.name or "Cup")
        lines = _podium(session, event_id)
    if not lines:
        return False
    embed = {
        "description": "\n".join([f"## 🏆 {name}", *lines]),
        "color": series_cards.COLOR,
    }
    text = f"**{name}** is over. The podium:"
    links = _link(event_id, "Results", "results")
    posted = _post_of(RESULT, event_id)
    if posted is None:
        return _send(RESULT, event_id, text, [embed], links)
    _, role = _settings()
    wait_for_channel(posted.channel_id)
    discord.edit_channel_message(
        posted.channel_id, posted.message_id, _message(role, text, [embed], links)
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
    session.execute(
        delete(DiscordPost).where(
            or_(
                and_(
                    col(DiscordPost.kind).in_((OPEN, REMIND, RESULT, EVENT)),
                    col(DiscordPost.subject_id) == event_id,
                ),
                about(DRAW, stages),
                about(ROUND, rounds),
                about(LEG_REMIND, legs),
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
        subscribed = session.get(AnnouncementSubscriber, member) is not None
    return AnnouncementState(available=True, subscribed=subscribed)


def subscribe(claims: dict[str, Any] | None, subscribed: bool) -> AnnouncementState:
    """Take or leave the announcement role. The role is written first, so a
    refusal changes nothing and the switch says it did not go through."""
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
        if subscribed and row is None:
            session.add(AnnouncementSubscriber(discord_id=member))
        elif not subscribed and row is not None:
            session.delete(row)
    return AnnouncementState(available=True, subscribed=subscribed)
